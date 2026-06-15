"""
使用者全域設定儲存庫 (Repository Pattern)。

集中管理 per-user 的全域偏好設定 ``user_settings.json``（存於使用者根目錄
``{ASSETS_DIR}/{user_id}/``，與各專案的 ``project_meta.json`` 分層）。目前承載三項偏好：

- ``auto_analyze_on_create``：建立新專案後是否自動分析素材（預設否，讓使用者先逐檔挑策略）。
- ``default_asset_strategy``：未逐檔設定的素材所套用的全域預設感知策略（simple / complex）。
- ``preference_capture_enabled``：是否用使用者編輯捕捉偏好資料以改進 AI（飛輪;opt-out，預設開）。

設計沿用 ``ProjectMetaStore`` 的三項保證：**原子寫入**（唯一 temp + ``os.replace``，杜絕 NFS 半寫）、
**容錯讀取**（缺檔 / 損毀回安全預設，不讓設定頁崩潰）、**交易式更新**（per-path 鎖序列化讀-改-寫，
杜絕併發 lost update）。設定本身以 pydantic ``UserSettings`` 型別化，邊界驗證集中於此。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from typing import Callable, Optional

from pydantic import BaseModel

from config.app_config import ASSETS_DIR

# 使用者全域設定檔名（單一事實來源）
USER_SETTINGS_FILENAME = "user_settings.json"

# 原子寫入的暫存檔副檔名
_TMP_SUFFIX = ".tmp"

# ── 設定預設值（具名常數，避免 magic value 散落）──────────────────────────────────
# 建立專案後是否自動分析素材：預設「否」，讓使用者有機會先逐檔決定 Strategy 再手動觸發分析。
DEFAULT_AUTO_ANALYZE_ON_CREATE = False
# 未逐檔設定的素材所套用的全域預設策略：預設 simple（本地 Qwen，快速且免 API 成本）。
DEFAULT_ASSET_STRATEGY = "simple"
# 是否用使用者的編輯捕捉偏好資料(飛輪)：預設「開」,採 opt-out;使用者可於設定頁關閉。
DEFAULT_PREFERENCE_CAPTURE_ENABLED = True


class UserSettings(BaseModel):
    """使用者全域偏好設定 (Value Object)；缺值時套用具名預設常數。"""

    # 建立新專案後是否自動分析素材
    auto_analyze_on_create: bool = DEFAULT_AUTO_ANALYZE_ON_CREATE
    # 未逐檔設定素材的全域預設感知策略（"simple" | "complex"）
    default_asset_strategy: str = DEFAULT_ASSET_STRATEGY
    # 是否用我的編輯捕捉偏好資料以改進 AI（飛輪;opt-out，預設開）
    preference_capture_enabled: bool = DEFAULT_PREFERENCE_CAPTURE_ENABLED


class UserSettingsStore:
    """``user_settings.json`` 的原子寫入 / 容錯讀取 / 交易式更新儲存庫。"""

    def __init__(self, base_dir: str = ASSETS_DIR) -> None:
        """設定使用者根目錄，並初始化 per-path 鎖登錄表（序列化同一檔的併發讀-改-寫）。"""
        self._base_dir = base_dir
        # 每個設定檔路徑一把鎖：併發更新據此序列化，杜絕 lost update
        self._locks: dict[str, threading.Lock] = {}
        # 保護 _locks 自身的延遲建立（臨界區極短）
        self._locks_guard = threading.Lock()

    def get(self, user_id: str) -> UserSettings:
        """讀取某使用者的全域設定；缺檔 / 損毀 / 欄位非法時回安全預設（不拋例外）。"""
        raw = self._read_path(self._settings_path(user_id))
        if not raw:
            return UserSettings()
        try:
            # pydantic 驗證 + 補齊缺漏欄位；非法值（如壞掉的 strategy）退回全域預設
            return UserSettings(**raw)
        except Exception:  # noqa: BLE001 - 任何驗證失敗都退回預設，避免設定頁 500
            return UserSettings()

    def update(self, user_id: str, mutator: Callable[[dict], None]) -> UserSettings:
        """
        於 per-path 鎖內原子地對設定做「讀-改-寫」交易，回傳更新後的 ``UserSettings``。

        ``mutator`` 就地修改既有設定 dict（已先以預設值補齊）；鎖確保整段交易不被併發打斷，
        每次落地都是完整檔。寫前確保使用者根目錄存在。
        """
        settings_path = self._settings_path(user_id)
        with self._lock_for(settings_path):
            # 以目前設定（含預設補齊）為基底，讓 mutator 永遠看到完整欄位
            current = self.get(user_id).model_dump()
            mutator(current)
            # 再過一次 pydantic 確保寫回的內容型別合法（也順手丟棄未知欄位）
            validated = UserSettings(**current)
            self._atomic_dump(settings_path, validated.model_dump())
            return validated

    # ── 內部工具 ──────────────────────────────────────────────────────────────

    def _settings_path(self, user_id: str) -> str:
        """取得某使用者的設定檔絕對路徑（使用者根目錄不存在時自動建立）。"""
        user_dir = os.path.join(self._base_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, USER_SETTINGS_FILENAME)

    def _lock_for(self, settings_path: str) -> threading.Lock:
        """取得某設定檔路徑專屬的鎖（不存在則延遲建立）；序列化該檔的併發更新。"""
        with self._locks_guard:
            lock = self._locks.get(settings_path)
            if lock is None:
                lock = threading.Lock()
                self._locks[settings_path] = lock
            return lock

    @staticmethod
    def _read_path(settings_path: str) -> Optional[dict]:
        """以絕對路徑讀設定；缺檔 / 無法讀取 / JSON 損毀一律回 ``None``（由呼叫端套預設）。"""
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _atomic_dump(settings_path: str, data: dict) -> None:
        """
        寫入**唯一** temp 檔再 ``os.replace`` 原子置換（同檔系上的置換具原子性）。

        temp 以 ``mkstemp`` 取唯一名而非固定 ``.tmp``：避免併發寫者互相截斷而換入損毀內容
        （與 ``ProjectMetaStore._atomic_dump`` 同手法）。
        """
        dir_name = os.path.dirname(settings_path) or "."
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_name, prefix=f"{USER_SETTINGS_FILENAME}.", suffix=_TMP_SUFFIX
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, settings_path)
        except BaseException:
            # 寫入 / 置換失敗：清掉殘留 temp，避免目錄堆積半寫檔，再把原例外拋回
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise


# 模組級單例（與 project_meta_store / cloud_ingestion_service 一致的使用慣例）
user_settings_store = UserSettingsStore()
