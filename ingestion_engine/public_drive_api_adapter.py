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
import re

import httpx

from config.ingestion_config import (
    DRIVE_API_BASE_URL,
    DRIVE_API_PAGE_SIZE,
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
# HTTP 錯誤判定門檻：>= 此值即視為失敗回應。
_HTTP_ERROR_THRESHOLD = 400
# 串流下載的暫存副檔名（下載完成才 rename，避免半截檔被誤判為已完成）。
_PARTIAL_SUFFIX = ".part"

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
        """以 alt=media 串流下載單檔到暫存檔，完成後 rename 成最終檔（避免半截檔）。"""
        url = f"{self._base_url}/files/{file_id}"
        params = {"alt": "media", "key": self._api_key}
        tmp_path = f"{dest_path}{_PARTIAL_SUFFIX}"
        try:
            with self._client.stream("GET", url, params=params) as resp:
                self._raise_for_status(resp.status_code, context=f"下載檔案 {file_id}")
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
            self._remove_quietly(tmp_path)
            raise

    def _get_json(self, url: str, params: dict, context: str) -> dict:
        """送出 GET 並回傳解析後 JSON；網路／逾時／HTTP／解析錯誤統一分類成攝取層例外。"""
        try:
            resp = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise RemoteAccessError(f"{context}逾時") from exc
        except httpx.RequestError as exc:
            raise RemoteAccessError(f"{context}失敗（網路錯誤）：{exc}") from exc
        self._raise_for_status(resp.status_code, context=context)
        try:
            return resp.json()
        except ValueError as exc:  # 含 json.JSONDecodeError
            raise RemoteAccessError(f"{context}：無法解析 Drive API 回應") from exc

    # ── 純函式工具 ────────────────────────────────────────────────────────────

    @staticmethod
    def _raise_for_status(status_code: int, context: str) -> None:
        """依 HTTP 狀態碼分類：401／403 → 授權失效；其餘 >=400 → 一般存取錯誤。"""
        if status_code in _AUTH_ERROR_STATUS:
            raise RemoteAuthError(
                f"{context}：授權／權限失效（HTTP {status_code}），"
                "請確認資料夾已設為「知道連結的人可檢視」且 API key 有效。"
            )
        if status_code >= _HTTP_ERROR_THRESHOLD:
            raise RemoteAccessError(f"{context}：Drive API 回應 HTTP {status_code}")

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
