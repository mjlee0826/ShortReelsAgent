"""
Stage 抽象:Pipeline 的最小執行單元 (Strategy / Command Pattern)。

每個 Stage 宣告自己屬於哪種資源(``ResourceType``),讓 ExecutorRegistry 能把它路由到對應的
Worker Pool(IO / CPU / GPU / API),達成「IO 與 GPU 同時工作、不互相阻塞」的重疊紅利。

Week 2a 只有 LegacyStage 一種具體 Stage;Week 2b/2c 會新增 DecodeStage / TechScoreStage 等細粒度 Stage,
全部沿用本介面,排程器與 Pipeline 邏輯完全不需改動。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from media_processor.pipeline.context import AssetContext


class ResourceType(Enum):
    """
    Stage 所需的資源種類,決定 ExecutorRegistry 路由到哪個 Worker Pool。

    不同 Pool 互不干擾,確保 IO(FFmpeg)與 GPU(推論)可同時進行。
    """

    IO = "io"     # FFmpeg subprocess、檔案讀寫、雲端上傳
    CPU = "cpu"   # cv2、KMeans、MediaPipe、SceneDetect
    GPU = "gpu"   # 所有本地 GPU 推論(與 ModelPool / GpuGate 整合)
    API = "api"   # 雲端 API 推論(Gemini),受 Semaphore 控 RPS


@dataclass(frozen=True)
class StageMeta:
    """
    Stage 的靜態描述 (Value Object)。

    ``name`` 用於進度事件與日誌標示;``resource_type`` 供 ExecutorRegistry 路由。
    frozen 確保可安全共享、可作為 dict key。
    """

    name: str
    resource_type: ResourceType


class StageError(Exception):
    """
    Stage 執行失敗的統一例外型別。

    Pipeline 會捕捉 Stage 內拋出的任何例外並包裝成本型別(或直接寫入 AssetContext.error),
    確保「單一 asset / 單一 Stage 失敗不影響其他 asset」(plan §6.5)。
    """

    def __init__(self, stage_name: str, message: str):
        """記錄出錯的 Stage 名稱與原始訊息,方便定位。"""
        self.stage_name = stage_name
        self.message = message
        super().__init__(f"[{stage_name}] {message}")


class Stage(ABC):
    """
    Pipeline 的最小執行單元抽象 (Strategy Pattern)。

    子類別實作 :meth:`run`,就地讀寫傳入的 ``AssetContext``。Stage 本身**不負責**
    進度事件、錯誤隔離或執行緒排程,那些橫切關注點由 Pipeline / Scheduler 統一處理,
    讓 Stage 實作保持單純(Single Responsibility)。
    """

    #: 子類別必須提供的靜態描述(名稱 + 資源型別)
    meta: StageMeta

    @abstractmethod
    def run(self, context: AssetContext) -> None:
        """
        執行本 Stage 的工作,結果就地寫入 ``context``。

        實作約定:
        - **不要**在此 catch 全部例外後吞掉;讓例外往上拋,由 Pipeline 統一隔離與記錄。
        - 只讀寫 ``context`` 中與本 Stage 相關的欄位,避免群組內 Stage 寫入同欄位衝突。
        """
