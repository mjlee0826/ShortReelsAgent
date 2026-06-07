"""
FrameAnalysis:單一 PIL 幀的分析結果容器,image 與 video 共用 (Value Object)。

設計動機
--------
影片的「代表幀」本質上就是一張圖,因此「對一張 PIL 幀做技術分 / 美學分 / 色彩特徵 / 臉部偵測」
這組 per-frame 分析,image(整張圖)與 video(中間代表幀)邏輯完全相同。把這些欄位抽成共用的
``FrameAnalysis``,讓 ``TechScoreStage`` / ``AesScoreStage`` / ``CVFeaturesStage`` /
``FaceDetectStage`` / ``RejectFilterStage`` 五個 Stage 變成 media-agnostic,image / video 直接共用、
影片端不必重寫一份。

- ``ImageWork`` 持有一個 FrameAnalysis(代表整張圖)。
- ``VideoWork`` 持有一個 FrameAnalysis(代表中間幀);saliency 聯集 / 逐 event bbox 屬影片專有,不放這裡。
- 共用 Stage 透過 :func:`get_frame_analysis` 取得當前 asset 的 FrameAnalysis,不需知道是 image 還是 video。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image

from media_processor.models import FaceInfo, SubjectBbox
from media_processor.pipeline.context import AssetContext, MediaKind


@dataclass
class FrameAnalysis:
    """
    一張 PIL 幀的 per-frame 分析結果(image 整張圖 / video 代表幀共用)。

    所有欄位帶預設值:當來源幀缺失(影片代表幀抽取失敗 → ``pil_image=None``)時,共用 Stage 會守門跳過,
    欄位維持預設,對齊原 processor 的 ``pil_mid is None`` 路徑。各共用 Stage 只寫入彼此互斥的欄位,平行安全。
    """

    pil_image: Optional[Image.Image] = None   # 待分析的 RGB PIL 幀(共同輸入)
    tech_score: float = 0.0                    # MUSIQ 技術分(原始值;Assembly 才 round)
    aes_score: float = 0.0                     # LAION 美學分(原始值)
    brightness: float = 0.0                    # 平均亮度 0–100
    color_temperature: str = ""                # warm / cool / neutral
    dominant_colors: list[str] = field(default_factory=list)  # 主色 hex 清單
    face_info: Optional[FaceInfo] = None       # 臉部數量 / 最大臉佔比摘要
    face_bbox: Optional[SubjectBbox] = None    # 最大臉 bbox(image 用以覆蓋 saliency;video 代表幀不採用)


def get_frame_analysis(context: AssetContext) -> FrameAnalysis:
    """
    取得當前 asset 的 ``FrameAnalysis``,供 media-agnostic 的共用 Stage 使用。

    依 ``media_kind`` 分派到 ImageWork.frame 或 VideoWork.frame。為避免與 ``image_work`` /
    ``video_work``(兩者 import 本模組的 FrameAnalysis)形成 import 循環,此處採延遲 import。
    """
    if context.media_kind == MediaKind.IMAGE:
        from media_processor.pipeline.work.image_work import get_image_work
        return get_image_work(context).frame
    from media_processor.pipeline.work.video_work import get_video_work
    return get_video_work(context).frame
