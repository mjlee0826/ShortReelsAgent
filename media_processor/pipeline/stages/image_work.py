"""
ImageWork:圖片各細粒度 Stage 之間傳遞的中間狀態容器 (Blackboard / Value Object Pattern)。

Week 2b 把 ``AbstractImageProcessor.process()`` 拆成 10 個 Stage 後,中間結果(解碼後的 PIL 圖、
各模型分數、bbox、cv 特徵、語意結果)需要在 Stage 間流動。本模組用一個 ``@dataclass`` 集中這些欄位,
存放在 ``AssetContext.scratch[IMAGE_WORK_KEY]``:

- **型別安全 + 契約集中**:取代裸 ``dict[str, Any]``,符合 CLAUDE.md「資料結構用 dataclass」。
- **群組內並行安全**:G3 平行群的各 Stage 只寫入**不同 attribute**(saliency 寫 ``saliency_bbox``、
  face 寫 ``face_bbox`` 等),彼此互斥;CPython GIL 下單一 attribute 賦值為原子操作,無 torn write。
- 欄位全帶預設值,Decode 之後的 Stage 漸進填入;最終由 AssemblyImageStage 一次讀齊組裝 metadata。

Week 2c 影片拆 Stage 時比照建立 ``VideoWork``,模式一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from PIL import Image

from media_processor.models import FaceInfo, SubjectBbox
from media_processor.pipeline.context import AssetContext

# AssetContext.scratch 中存放 ImageWork 的唯一鍵;集中為常數避免 magic string 散落各 Stage
IMAGE_WORK_KEY = "image"


@dataclass
class ImageWork:
    """
    單張圖片流經各 Stage 時的中間產物集合。

    Decode 建立並填入基本欄位(pil_image / 尺寸),後續 Stage 各自補上對應 attribute,
    AssemblyImageStage 讀齊全部組成 ``ImageMetadata``。所有欄位帶預設值,確保部分 Stage
    因 Early Rejection 未執行時仍是合法物件(雖然 reject 後不會走到 Assembly)。
    """

    # ── DecodeImageStage 產出(其餘 Stage 的共同輸入)──────────────────────────
    pil_image: Optional[Image.Image] = None  # 已 convert("RGB") 的來源圖
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0

    # ── 品質評分 ──────────────────────────────────────────────────────────────
    tech_score: float = 0.0  # MUSIQ 原始技術分(reject 用原值,metadata 才 round)
    aes_score: float = 0.0   # LAION 原始美學分

    # ── 主體定位(saliency 與 face 分別寫,Assembly 才決定誰覆蓋誰)─────────────
    saliency_bbox: Optional[SubjectBbox] = None  # U2-Net 顯著性 bbox
    face_bbox: Optional[SubjectBbox] = None       # 最大臉 bbox;有臉時 Assembly 用它覆蓋 saliency
    face_info: Optional[FaceInfo] = None          # 臉部數量 / 最大臉佔比摘要

    # ── 視覺特徵(cv2 / PIL)──────────────────────────────────────────────────
    brightness: float = 0.0
    color_temperature: str = ""
    dominant_colors: list[str] = field(default_factory=list)

    # ── EXIF 與語意 ───────────────────────────────────────────────────────────
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
