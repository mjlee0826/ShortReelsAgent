"""
公開資料夾 Google Drive 存取 adapter (Adapter Pattern)。

以 Drive API v3 + 一把全站共用的 `GOOGLE_API_KEY` 存取「知道連結的人可檢視」
(anyone-with-the-link) 的公開資料夾：無同意畫面、不綁帳號、非 per-user，零 OAuth、零 token。
位址以資料夾／檔案 ID 表達（即 `CloudStorageAdapter` 的不透明 locator）。

httpx client 可由外部注入，方便測試時以 `httpx.MockTransport` 餵 canned JSON 驗解析/分頁/
下載/錯誤分類，而不需真連網路。
"""
from __future__ import annotations

import os
import random
import re
import time
from typing import Callable, TypeVar

import httpx

from config.ingestion_config import (
    DRIVE_API_BASE_URL,
    DRIVE_API_MAX_RETRIES,
    DRIVE_API_PAGE_SIZE,
    DRIVE_API_RETRY_BACKOFF_MULTIPLIER,
    DRIVE_API_RETRY_BASE_BACKOFF_SEC,
    DRIVE_API_RETRY_JITTER_RATIO,
    DRIVE_API_RETRY_MAX_BACKOFF_SEC,
    DRIVE_API_TIMEOUT_SEC,
    DRIVE_FOLDER_MIMETYPE,
    GOOGLE_API_KEY,
    INGESTION_MEDIA_EXTENSIONS,
)
from ingestion_engine.cloud_storage_adapter import CloudStorageAdapter
from ingestion_engine.exceptions import IngestionError, RemoteAccessError, RemoteAuthError
from ingestion_engine.models import RemoteEntry

# 視為「授權／權限失效」的 HTTP 狀態碼（API key 對非公開檔案無效、資料夾轉私人皆落此）。
_AUTH_ERROR_STATUS = (401, 403)
# HTTP「請求過多」狀態碼：明確的限流訊號，一律視為暫時性、可退避重試。
_HTTP_TOO_MANY_REQUESTS = 429
# HTTP 錯誤判定門檻：>= 此值即視為失敗回應。
_HTTP_ERROR_THRESHOLD = 400
# Drive API 在 403 回應 body 中代表「限流／配額用盡」(而非真權限不足) 的 error reason 集合；
# 命中這些 reason 的 403 屬暫時性，須退避重試而非當成授權失效把專案永久暫停。
_RATE_LIMIT_REASONS = frozenset({
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "dailyLimitExceeded",
    "sharingRateLimitExceeded",
    "quotaExceeded",
})
# 串流下載的暫存副檔名（下載完成才 rename，避免半截檔被誤判為已完成）。
_PARTIAL_SUFFIX = ".part"
# 診斷用：印出 Drive API 錯誤回應 body 時的最大字元數（避免超長 body 洗版 console）。
_ERROR_BODY_SNIPPET_LEN = 300

# 「執行一次嘗試」callable 的回傳型別變數，供 _with_retry 泛型保留 attempt 的回傳型別。
_T = TypeVar("_T")


class _RateLimitedError(RemoteAccessError):
    """
    內部訊號例外：Drive API 限流（rate limit／quota）→ 屬暫時性，供 _with_retry 退避重試。

    刻意設為 RemoteAccessError 子類：即使重試耗盡逸出本 adapter，同步協調層也只會標 error、
    下輪 poller 重試，絕不會被當成授權失效（RemoteAuthError）而把專案永久暫停。
    """

# 無法解析資料夾 ID 時回給使用者的提示。
DRIVE_URL_HINT = (
    "無法從連結解析出 Google Drive 資料夾 ID，"
    "請貼上資料夾的分享連結（例：https://drive.google.com/drive/folders/XXXXXXXX）。"
)

# 從各種 Drive 資料夾 URL 形式抽出 ID 的樣式。
_FOLDER_ID_PATTERN = re.compile(r"/folders/([A-Za-z0-9_-]+)")   # /drive/folders/{ID}、/u/0/folders/{ID}
_ID_QUERY_PATTERN = re.compile(r"[?&]id=([A-Za-z0-9_-]+)")      # open?id={ID}、?id={ID}
_BARE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")             # 直接貼裸資料夾 ID


class PublicDriveApiAdapter(CloudStorageAdapter):
    """以 Drive API v3 + 共用 API key 存取公開（anyone-with-link）資料夾的 adapter。"""

    def __init__(
        self,
        api_key: str = GOOGLE_API_KEY,
        base_url: str = DRIVE_API_BASE_URL,
        page_size: int = DRIVE_API_PAGE_SIZE,
        timeout_sec: int = DRIVE_API_TIMEOUT_SEC,
        client: httpx.Client | None = None,
    ):
        """記錄 API key 與 Drive API 端點設定；client 未注入時自建一個帶逾時的 httpx.Client。"""
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._client = client if client is not None else httpx.Client(timeout=timeout_sec)

    # ── 公開介面 ──────────────────────────────────────────────────────────────

    def parse_source(self, source_url: str) -> str:
        """從 Drive 資料夾 URL（或裸 ID）解析出資料夾 ID；無法解析時 raise ValueError。"""
        spec = (source_url or "").strip()
        if not spec:
            raise ValueError("來源不能為空，請貼上 Google Drive 資料夾連結。")
        # 非網址且整串就是合法 ID 字元 → 視為使用者直接貼了資料夾 ID
        if "://" not in spec and _BARE_ID_PATTERN.match(spec):
            return spec
        for pattern in (_FOLDER_ID_PATTERN, _ID_QUERY_PATTERN):
            matched = pattern.search(spec)
            if matched:
                return matched.group(1)
        raise ValueError(DRIVE_URL_HINT)

    def list_files(self, folder_locator: str) -> list[RemoteEntry]:
        """列出資料夾一層內的媒體檔（排除子資料夾，並套副檔名白名單）。"""
        entries: list[RemoteEntry] = []
        for item in self._list_children(folder_locator):
            if item.get("mimeType") == DRIVE_FOLDER_MIMETYPE:
                continue  # 子資料夾不列入（壓平模型：只取本資料夾的檔案）
            if not self._is_media(item.get("name", "")):
                continue  # 非媒體雜檔（文件／壓縮檔）略過
            entries.append(self._to_entry(item))
        return entries

    def download_folder(self, folder_locator: str, dest_dir: str) -> None:
        """把資料夾內媒體檔增量下載到 dest_dir（本地已存在且同大小者跳過）。"""
        os.makedirs(dest_dir, exist_ok=True)
        for entry in self.list_files(folder_locator):
            dest_path = os.path.join(dest_dir, entry.name)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) == entry.size:
                continue  # 增量：大小一致視為未變動，省下重複下載
            self._download_file(entry.locator, dest_path)

    # ── Drive API 呼叫 ─────────────────────────────────────────────────────────

    def _list_children(self, folder_locator: str) -> list[dict]:
        """分頁列出資料夾的直接子項目原始 dict（處理 nextPageToken 直到取完）。"""
        children: list[dict] = []
        page_token: str | None = None
        while True:
            params = {
                "q": f"'{folder_locator}' in parents and trashed=false",
                "key": self._api_key,
                "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)",
                "pageSize": self._page_size,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get_json(f"{self._base_url}/files", params, context="列出資料夾")
            children.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return children

    def _download_file(self, file_id: str, dest_path: str) -> None:
        """以 alt=media 串流下載單檔到暫存檔，完成後 rename 成最終檔；遇限流退避重試（避免半截檔）。"""
        url = f"{self._base_url}/files/{file_id}"
        params = {"alt": "media", "key": self._api_key}
        tmp_path = f"{dest_path}{_PARTIAL_SUFFIX}"
        context = f"下載檔案 {file_id}"

        def _attempt() -> None:
            """單次下載嘗試；任何攝取層例外（含限流訊號）發生前先清半截暫存檔再上拋。"""
            try:
                with self._client.stream("GET", url, params=params) as resp:
                    self._classify_http_error(resp, context=context)
                    with open(tmp_path, "wb") as handle:
                        for chunk in resp.iter_bytes():
                            handle.write(chunk)
                os.replace(tmp_path, dest_path)
            except httpx.TimeoutException as exc:
                self._remove_quietly(tmp_path)
                raise RemoteAccessError(f"下載檔案逾時：{file_id}") from exc
            except httpx.RequestError as exc:
                self._remove_quietly(tmp_path)
                raise RemoteAccessError(f"下載檔案失敗（網路錯誤）：{file_id}：{exc}") from exc
            except IngestionError:
                # 含限流 _RateLimitedError：先清半截暫存檔再上拋（限流者由 _with_retry 退避後重試）
                self._remove_quietly(tmp_path)
                raise

        self._with_retry(_attempt, context=context)

    def _get_json(self, url: str, params: dict, context: str) -> dict:
        """送出 GET 並回傳解析後 JSON；遇限流退避重試，網路／逾時／HTTP／解析錯誤統一分類成攝取層例外。"""

        def _attempt() -> dict:
            """單次列檔請求嘗試；回傳解析後 JSON 或上拋分類後的攝取層例外。"""
            try:
                resp = self._client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise RemoteAccessError(f"{context}逾時") from exc
            except httpx.RequestError as exc:
                raise RemoteAccessError(f"{context}失敗（網路錯誤）：{exc}") from exc
            self._classify_http_error(resp, context=context)
            try:
                return resp.json()
            except ValueError as exc:  # 含 json.JSONDecodeError
                raise RemoteAccessError(f"{context}：無法解析 Drive API 回應") from exc

        return self._with_retry(_attempt, context)

    # ── 錯誤分類與退避重試 ─────────────────────────────────────────────────────

    def _with_retry(self, attempt: Callable[[], _T], context: str) -> _T:
        """
        執行 attempt()，對「限流」(_RateLimitedError) 指數退避＋抖動重試；其餘錯誤立即上拋。

        重試耗盡仍限流時，以 RemoteAccessError（暫時性）上拋——交給同步協調層標 error、下輪
        poller 重試，絕不冒充 RemoteAuthError 把專案永久暫停。在工作執行緒內以 time.sleep 阻塞
        等待（sync_project 經 asyncio.to_thread 執行，不卡 event loop）。
        """
        backoff_sec = DRIVE_API_RETRY_BASE_BACKOFF_SEC
        for attempt_index in range(DRIVE_API_MAX_RETRIES + 1):
            try:
                return attempt()
            except _RateLimitedError as exc:
                if attempt_index >= DRIVE_API_MAX_RETRIES:
                    raise RemoteAccessError(
                        f"{context}：Drive API 持續限流，已重試 {DRIVE_API_MAX_RETRIES} 次仍失敗，"
                        "稍後將自動再嘗試。"
                    ) from exc
                wait_sec = self._backoff_with_jitter(backoff_sec)
                print(
                    f"[PublicDriveApi] ⏳ {context} 遇限流，{wait_sec:.1f}s 後重試"
                    f"（{attempt_index + 1}/{DRIVE_API_MAX_RETRIES}）：{exc}"
                )
                time.sleep(wait_sec)
                backoff_sec *= DRIVE_API_RETRY_BACKOFF_MULTIPLIER

    def _classify_http_error(self, resp: httpx.Response, context: str) -> None:
        """
        依 HTTP 狀態碼 + Drive API 錯誤原因把失敗回應分流成對應例外（2xx 直接放行）。

        關鍵分流：403 可能是「真權限不足」也可能是「限流／配額用盡」，後者 body 的
        error.errors[].reason 落在 _RATE_LIMIT_REASONS。限流（含 HTTP 429）一律丟
        _RateLimitedError（暫時性 → 由 _with_retry 退避重試），唯有真權限不足才丟
        RemoteAuthError，避免暫時性限流被誤判成授權失效而把專案永久暫停。
        """
        status_code = resp.status_code
        if status_code < _HTTP_ERROR_THRESHOLD:
            return
        reason = self._extract_error_reason(resp)
        # 診斷：把 Drive API 真正回的 status / reason / body 印出來，便於分辨「限流」vs「真授權」根因
        print(
            f"[PublicDriveApi] ⚠️ {context}：HTTP {status_code} reason={reason!r} "
            f"body={self._body_snippet(resp)!r}"
        )
        is_rate_limited = status_code == _HTTP_TOO_MANY_REQUESTS or (
            status_code in _AUTH_ERROR_STATUS and reason in _RATE_LIMIT_REASONS
        )
        if is_rate_limited:
            detail = f" / {reason}" if reason else ""
            raise _RateLimitedError(f"{context}：Drive API 限流（HTTP {status_code}{detail}）")
        if status_code in _AUTH_ERROR_STATUS:
            raise RemoteAuthError(
                f"{context}：授權／權限失效（HTTP {status_code}），"
                "請確認資料夾已設為「知道連結的人可檢視」且 API key 有效。"
            )
        raise RemoteAccessError(f"{context}：Drive API 回應 HTTP {status_code}")

    # ── 純函式工具 ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_error_reason(resp: httpx.Response) -> str | None:
        """
        從 Drive API 錯誤回應 body 取出第一個 error.errors[].reason（取不到再退取 error.status）。

        串流下載的回應 body 尚未載入，需先 read() 才能解析（對一般回應為冪等）；任何解析失敗都
        回 None（讓呼叫端退回純狀態碼分類），best-effort 不得掩蓋原本要回報的 HTTP 錯誤。
        """
        try:
            resp.read()  # 串流回應先把（通常很小的）錯誤 body 讀進來；一般回應已讀取，呼叫冪等
            body = resp.json()
        except (ValueError, RuntimeError, httpx.HTTPError):
            return None
        if not isinstance(body, dict):
            return None
        error = body.get("error")
        if not isinstance(error, dict):
            return None
        errors = error.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = errors[0].get("reason")
            if reason:
                return reason
        # 新式錯誤格式可能只帶 status 字串（如 "RESOURCE_EXHAUSTED"）
        status = error.get("status")
        return status if isinstance(status, str) else None

    @staticmethod
    def _body_snippet(resp: httpx.Response) -> str:
        """回傳錯誤回應 body 的截斷文字片段（診斷用）；body 尚未讀取或解碼失敗回佔位字串。"""
        try:
            text = resp.text
        except (RuntimeError, httpx.HTTPError):
            return "<unread>"
        snippet = text[:_ERROR_BODY_SNIPPET_LEN].replace("\n", " ").strip()
        return snippet or "<empty>"

    @staticmethod
    def _backoff_with_jitter(base_backoff_sec: float) -> float:
        """把基礎退避秒數夾在上限內，再套 ±JITTER_RATIO 隨機抖動，打散多專案同步退避尖峰。"""
        capped = min(base_backoff_sec, DRIVE_API_RETRY_MAX_BACKOFF_SEC)
        jitter = capped * DRIVE_API_RETRY_JITTER_RATIO
        return max(0.0, capped + random.uniform(-jitter, jitter))

    @staticmethod
    def _to_entry(item: dict) -> RemoteEntry:
        """把 Drive API files() 的單筆 dict 映射為 RemoteEntry（容忍缺欄位）。"""
        return RemoteEntry(
            name=item.get("name", ""),
            locator=item.get("id", ""),
            is_dir=item.get("mimeType") == DRIVE_FOLDER_MIMETYPE,
            size=int(item.get("size") or 0),
            mod_time=item.get("modifiedTime"),
        )

    @staticmethod
    def _is_media(name: str) -> bool:
        """判斷檔名副檔名是否屬於攝取的媒體白名單。"""
        return os.path.splitext(name)[1].lower() in INGESTION_MEDIA_EXTENSIONS

    @staticmethod
    def _remove_quietly(path: str) -> None:
        """刪除暫存檔，忽略不存在或刪除失敗（清理用，不應掩蓋主錯誤）。"""
        try:
            os.remove(path)
        except OSError:
            pass
