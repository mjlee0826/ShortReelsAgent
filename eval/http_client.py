"""帶 retry / 429 退避 / 粗略 rate limiting 的 HTTP 客戶端。

封裝 ``requests.Session``（比照 ``music_engine/jamendo_adapter.py`` 的 REST 查詢 + streaming
下載風格），對外提供 ``get_json`` 與 ``download`` 兩個方法；下載採 ``.part`` 暫存後 rename 的
原子寫，避免半截檔被當成完成。
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import requests

from .constants import (
    DOWNLOAD_CHUNK_SIZE,
    DOWNLOAD_TIMEOUT_SEC,
    HTTP_STATUS_TOO_MANY_REQUESTS,
    HTTP_TIMEOUT_SEC,
    INTER_REQUEST_DELAY_SEC,
    MAX_RETRY_ATTEMPTS,
    PARTIAL_SUFFIX,
    RETRY_AFTER_HEADER,
    RETRY_BACKOFF_BASE_SEC,
    RETRY_BACKOFF_MAX_SEC,
    RETRY_JITTER_SEC,
    RETRYABLE_STATUS_CODES,
)
from .logging_setup import get_logger

logger = get_logger(__name__)


class RetryingHttpClient:
    """可重試的 HTTP 客戶端（Adapter over requests）。

    - 對網路錯誤與可重試狀態碼（429/5xx）做指數退避重試；429 優先採用 ``Retry-After``。
    - 相鄰請求間維持最小間隔做粗略 rate limiting。
    """

    def __init__(
        self,
        *,
        timeout: float = HTTP_TIMEOUT_SEC,
        download_timeout: float = DOWNLOAD_TIMEOUT_SEC,
        max_attempts: int = MAX_RETRY_ATTEMPTS,
        backoff_base: float = RETRY_BACKOFF_BASE_SEC,
        backoff_max: float = RETRY_BACKOFF_MAX_SEC,
        inter_request_delay: float = INTER_REQUEST_DELAY_SEC,
    ) -> None:
        """初始化共用 session 與重試參數。"""
        self._session = requests.Session()
        self._timeout = timeout
        self._download_timeout = download_timeout
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._inter_request_delay = inter_request_delay
        self._last_request_at = 0.0  # 上次發出請求的時間（rate limiting 用）

    # ────────────────────────────── 對外方法 ──────────────────────────────
    def get_json(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        """GET 並回傳 JSON dict（帶重試）。"""
        response = self._request_with_retry(
            "GET", url, params=params, headers=headers, timeout=self._timeout, stream=False
        )
        return response.json()

    def download(self, url: str, dest_path: Path, *, headers: dict | None = None) -> None:
        """streaming 下載到 ``dest_path``（原子寫 + 重試）。"""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_name(dest_path.name + PARTIAL_SUFFIX)

        response = self._request_with_retry(
            "GET", url, params=None, headers=headers, timeout=self._download_timeout, stream=True
        )
        try:
            with open(tmp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)
        finally:
            response.close()
        # 全部寫完才 rename 成正式檔（原子）；若中途失敗，留下 .part 不會被誤認完成
        tmp_path.replace(dest_path)

    # ────────────────────────────── 內部實作 ──────────────────────────────
    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: dict | None,
        headers: dict | None,
        timeout: float,
        stream: bool,
    ) -> requests.Response:
        """共用的重試迴圈；回傳成功的 Response，否則拋出最後一次例外。"""
        last_exc: Exception | None = None
        for attempt in range(self._max_attempts):
            self._respect_rate_limit()
            try:
                response = self._session.request(
                    method, url, params=params, headers=headers, timeout=timeout, stream=stream
                )
            except requests.RequestException as exc:  # 連線/逾時等網路錯誤 → 可重試
                last_exc = exc
                self._sleep_before_retry(attempt, retry_after=None)
                logger.warning("請求失敗（網路錯誤），重試 %d/%d：%s", attempt + 1, self._max_attempts, exc)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                retry_after = self._parse_retry_after(response)
                last_exc = requests.HTTPError(f"{response.status_code} for {url}", response=response)
                # 達最後一次嘗試就不再睡，直接走下方 raise
                if attempt < self._max_attempts - 1:
                    self._sleep_before_retry(attempt, retry_after=retry_after)
                    logger.warning(
                        "狀態碼 %d 可重試，重試 %d/%d（url=%s）",
                        response.status_code, attempt + 1, self._max_attempts, url,
                    )
                    continue

            # 非可重試的 4xx/5xx 直接拋；2xx 正常回傳
            response.raise_for_status()
            return response

        # 迴圈跑完仍未成功（最後一次是可重試狀態碼或網路錯誤）
        assert last_exc is not None
        raise last_exc

    def _respect_rate_limit(self) -> None:
        """確保與上一次請求至少間隔 ``inter_request_delay`` 秒。"""
        if self._inter_request_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait = self._inter_request_delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _sleep_before_retry(self, attempt: int, *, retry_after: float | None) -> None:
        """退避睡眠：優先採用伺服器給的 Retry-After，否則指數退避 + 抖動。"""
        if retry_after is not None:
            delay = retry_after
        else:
            delay = min(self._backoff_base * (2 ** attempt), self._backoff_max)
            delay += random.uniform(0.0, RETRY_JITTER_SEC)
        time.sleep(delay)

    @staticmethod
    def _parse_retry_after(response: requests.Response) -> float | None:
        """解析 429 的 ``Retry-After``（秒）；無或非數字則回 None。"""
        if response.status_code != HTTP_STATUS_TOO_MANY_REQUESTS:
            return None
        raw = response.headers.get(RETRY_AFTER_HEADER)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            # Retry-After 也可能是 HTTP date 格式；此處不細究，退回指數退避
            return None
