"""
攝取層資料結構與具名常數 (Value Object Pattern)。

以 pydantic 定義雲端列檔結果與同步報告等不可變事實，讓 adapter／service／poller／API
之間以結構化型別溝通，避免裸 dict 散落。雲端來源與同步狀態折進各 project 的
`project_meta.json`（不另建註冊檔），本檔集中定義其欄位鍵與狀態列舉的具名常數，杜絕散落的
magic string。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

# ── 雲端來源標記（寫入 project_meta.json 的 source 欄位）─────────────────────────
SOURCE_GDRIVE = "gdrive"  # 由 Drive 公開資料夾 URL 建立並背景同步的 project

# ── 雲端同步生命週期狀態（寫入 project_meta.json，供 REST 觀測）────────────────────
SYNC_STATUS_ACTIVE = "active"                   # 正常同步中
SYNC_STATUS_PAUSED_AUTH = "paused_auth_error"   # 授權失效，暫停同步（其他 project 不受影響）
SYNC_STATUS_ERROR = "error"                     # 其他同步錯誤（暫時性，下輪會重試）

# ── project 的 Phase 1 背景預跑狀態（寫入 project_meta.json，供 REST 觀測）──────────
PHASE1_STATUS_PENDING = "pending"        # 已建 project，尚未開始分析
PHASE1_STATUS_PROCESSING = "processing"  # Phase 1 進行中
PHASE1_STATUS_DONE = "done"              # Phase 1 完成
PHASE1_STATUS_FAILED = "failed"          # Phase 1 失敗
# 已下載素材，但依使用者設定「建立後不自動分析」而刻意略過 Phase 1，待使用者到素材頁手動觸發。
# 與 DONE 同視為「已收斂」，避免背景 poller 每輪重複觸發分析。
PHASE1_STATUS_SKIPPED = "skipped"

# ── project_meta.json 內雲端相關欄位鍵（具名常數，避免 magic string）──────────────
META_KEY_SOURCE = "source"                          # 來源標記（SOURCE_GDRIVE）
META_KEY_DRIVE_FOLDER_ID = "drive_folder_id"        # Drive 資料夾 ID（locator）
META_KEY_SOURCE_URL = "source_url"                  # 使用者原始貼上的 Drive 資料夾 URL（存證）
META_KEY_PHASE1_STATUS = "phase1_status"            # Phase 1 背景預跑狀態
META_KEY_PHASE1_UPDATED_AT = "phase1_updated_at"    # Phase 1 狀態最後更新時間
META_KEY_LAST_SIGNATURE = "last_asset_signature"    # 上次同步的素材簽章（檔名+大小+修改時間 hash）
# 上次同步成功時的每檔遠端指紋 {檔名: "size:mod_time"}；供 _reconcile 比對出「被移除 / 被同名替換」的素材
META_KEY_REMOTE_MANIFEST = "remote_manifest"
META_KEY_LAST_SYNCED_AT = "last_synced_at"          # 上次同步完成時間
META_KEY_SYNC_STATUS = "sync_status"                # 雲端同步狀態
META_KEY_LAST_SYNC_ERROR = "last_sync_error"        # 上次同步錯誤訊息（成功時清空）
# 建立專案當下「是否自動分析」的快照（取自全域使用者設定）；sync/poller 據此決定是否觸發 Phase 1。
# 缺鍵時視為 True，讓本欄位導入前建立的舊專案維持原本「自動分析」行為（零破壞）。
META_KEY_AUTO_ANALYZE = "auto_analyze"
# 進行中 Phase 1 背景 job 的 id；由 backend 側 _phase1_runner 在開跑前寫入、收尾清除。
# 素材頁掛載時據此訂閱 /ws/progress/{job_id}，讓背景同步的分析也能像手動重分析一樣顯示即時進度。
META_KEY_ACTIVE_PHASE1_JOB_ID = "active_phase1_job_id"


def _now_iso() -> str:
    """回傳 UTC ISO8601 時間字串（與 projects.py / director_service 的時間格式一致）。"""
    return datetime.now(timezone.utc).isoformat()


class RemoteEntry(BaseModel):
    """雲端某資料夾下單一項目的列檔結果（由 adapter 解析雲端 API 回應而來）。"""

    name: str                       # 項目名稱（不含路徑）
    locator: str                    # adapter 不透明位址（Drive = 檔案／資料夾 ID）
    is_dir: bool = False            # 是否為資料夾
    size: int = 0                   # 檔案大小（bytes）；資料夾為 0
    mod_time: Optional[str] = None  # 最後修改時間（雲端提供的 ISO 字串）


class SyncReport(BaseModel):
    """單次 project 雲端同步的結果摘要（回給手動 sync 端點，也供日誌）。"""

    project_name: str
    sync_status: str                                # 同步後的 sync_status
    downloaded: bool = False                            # 本次是否有偵測到變動並下載新素材
    phase1_ran: bool = False                             # 本次是否觸發了 Phase 1
    errors: list[str] = Field(default_factory=list)     # 過程中的非致命錯誤訊息
