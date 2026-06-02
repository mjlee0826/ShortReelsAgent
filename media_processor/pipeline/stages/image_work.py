"""
ImageWork:圖片各細粒度 Stage 之間傳遞的中間狀態容器 (Blackboard / Value Object Pattern)。

Week 2b 把 ``AbstractImageProcessor.process()`` 拆成多個 Stage 後,中間結果需在 Stage 間流動,
集中存放於 ``AssetContext.scratch[IMAGE_WORK_KEY]``。

Week 2c 重構:把「對一張 PIL 幀的 per-frame 分析」(pil_image / tech / aes / 色彩 / 臉)抽到共用的
:class:`~media_processor.pipeline.stages.frame_analysis.FrameAnalysis`,改由 ``ImageWork.frame`` 持有,
讓 image / video 共用同一組 per-frame Stage(TechScore / AesScore / CVFeatures / FaceDetect / RejectFilter)。
ImageWork 自身只保留圖片**專有**的欄位:整張圖尺寸、整張圖 saliency bbox、EXIF、語意結果。

- **型別安全 + 契約集中**:取代裸 ``dict``,符合 CLAUDE.md「資料結構用 dataclass」。
- **群組內並行安全**:共用 Stage 各寫 ``frame`` 的不同 attribute、image 專屬 Stage 各寫 ImageWork 不同 attribute,
  彼此互斥;CPython GIL 下單一 attribute 賦值為原子操作,無 torn write。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from media_processor.models import SubjectBbox
from media_processor.pipeline.context import AssetContext
from media_processor.pipeline.stages.frame_analysis import FrameAnalysis

# AssetContext.scratch 中存放 ImageWork 的唯一鍵;集中為常數避免 magic string 散落各 Stage
IMAGE_WORK_KEY = "image"


@dataclass
class ImageWork:
    """
    單張圖片流經各 Stage 時的中間產物集合。

    ``frame`` 由 DecodeImageStage 建立(整張圖即「代表幀」),共用的 per-frame Stage 填入其欄位;
    image 專屬欄位(saliency_bbox / exif / vlm_result)由對應 image Stage 填入。
    AssemblyImageStage 讀齊 ``frame`` + 專屬欄位組成 ``ImageMetadata``。所有欄位帶預設值。
    """

    # 整張圖的 per-frame 分析(pil_image + tech/aes/色彩/臉);共用 Stage 寫入
    frame: FrameAnalysis = field(default_factory=FrameAnalysis)
    # 整張圖尺寸(DecodeImageStage 產出)
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    # 主體定位(image 專有:整張圖 U2-Net saliency;有臉時 Assembly 以 frame.face_bbox 覆蓋)
    saliency_bbox: Optional[SubjectBbox] = None
    # EXIF 與語意(image 專有)
    exif: dict[str, Any] = field(default_factory=dict)        # {"datetime": ..., "gps_info": ...}
    vlm_result: dict[str, Any] = field(default_factory=dict)  # Qwen / Gemini 回傳的語意欄位


def get_image_work(context: AssetContext) -> ImageWork:
    """
    從 ``context.scratch`` 取出本 asset 的 ImageWork(DecodeImageStage 已建立)。

    缺少時拋出明確錯誤而非 KeyError,方便定位「Decode 未先執行」的編排錯誤;
    此例外會被 Pipeline 的 ``_run_stage`` 統一隔離成該 asset 的 error 狀態。
    """
    work = context.scratch.get(IMAGE_WORK_KEY)
    if work is None:
        raise RuntimeError(
            f"ImageWork 尚未建立(asset={context.asset_id});DecodeImageStage 必須先於其他圖片 Stage 執行"
        )
    return work
