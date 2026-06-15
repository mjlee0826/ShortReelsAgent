"""
進度事件的資料定義（Value Object）。

只放「事件長什麼樣」── 事件型態列舉與不可變事件物件，
不含廣播或觀察邏輯（那是 ``tracker`` / ``observer`` 的職責）。
拆出獨立模組後，新增事件欄位或型態不會牽動 Subject 與各 Observer 實作。
"""
import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ProgressEventType(str, Enum):
    """所有 Pipeline 階段可能產生的事件型態。"""

    # ── Stage 級別 ────────────────────────────────────────────────────────────
    STAGE_START  = "stage_start"
    STAGE_FINISH = "stage_finish"
    STAGE_ERROR  = "stage_error"

    # ── Pipeline 級別（單一 asset 的一條流水線起訖） ──────────────────────────
    PIPELINE_START  = "pipeline_start"
    PIPELINE_FINISH = "pipeline_finish"

    # ── Job 級別（一次 generate 請求的工作流終端訊號，涵蓋 Phase 1–4） ────────
    # 與 per-asset 的 PIPELINE_FINISH 區隔：前端據此關閉進度面板並取最終結果
    JOB_FINISHED = "job_finished"
    JOB_ERROR    = "job_error"

    # ── 啟動期 ────────────────────────────────────────────────────────────────
    # Eager warm up 模型載入事件，由 ModelPoolRegistry.warm_up 發送
    MODEL_WARMUP = "model_warmup"

    # ── 資源等待（ModelPool.borrow 即時 VRAM 重檢） ────────────────────────────
    # 借出 GPU 模型前真實 free VRAM 不足而阻塞 / 騰出，讓前端顯示「等待 GPU 資源」
    RESOURCE_WAIT     = "resource_wait"
    RESOURCE_ACQUIRED = "resource_acquired"

    # ── 導演 agentic loop（Phase 4）：思考串流 / 工具呼叫旁白 / 中途提問 ────────────
    # 導演多輪 tool-use 過程的即時認知串流，前端據此在聊天面板呈現「思考 / 動作 / 提問」
    DIRECTOR_THINKING_DELTA       = "director_thinking_delta"
    DIRECTOR_TOOL_CALL            = "director_tool_call"
    # 導演呼叫 ask_user 暫停、等待使用者回答（B2 suspend/resume 的軟終端訊號）
    DIRECTOR_CLARIFICATION_NEEDED = "director_clarification_needed"


class ProgressEvent(BaseModel):
    """
    Pipeline 進度事件（不可變值物件）。

    序列化策略：WebSocket 可直接呼叫 ``event.model_dump_json()`` 推給前端。
    """

    event_type: ProgressEventType
    # 一次完整 generate 請求對應一個 job_id；由 Tracker 建構時帶入
    job_id: Optional[str] = None
    # 多 asset 場景下 stage 事件需區分屬於哪個 asset；Pipeline 級別事件可空
    asset_id: Optional[str] = None
    # Stage 名稱（例如 "decode_image" / "semantic_image"）；非 stage 事件可空
    stage_name: Optional[str] = None
    # 事件發生時刻（unix 秒，預設取建立時當下）
    timestamp: float = Field(default_factory=time.time)
    # STAGE_FINISH / PIPELINE_FINISH 帶入該階段耗時（毫秒）
    duration_ms: Optional[float] = None
    # 任意額外資訊（例如 model 名稱、batch 大小、score 等）
    payload: dict[str, Any] = Field(default_factory=dict)
    # STAGE_ERROR 帶入錯誤訊息（保留 raw 字串，前端決定如何顯示）
    error: Optional[str] = None
