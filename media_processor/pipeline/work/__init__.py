"""
media_processor.pipeline.work 套件:Stage 之間流動的中間狀態容器 (Blackboard / Value Object)。

這裡放的是「資料結構」而非 Stage:
- ``FrameAnalysis``:單張 PIL 幀的 per-frame 分析結果(image 整張圖 / video 代表幀共用)。
- ``ImageWork`` / ``VideoWork``:圖片 / 影片各自專有欄位的中間容器,存於 ``AssetContext.scratch``。

注意 import 順序:``frame_analysis`` 必須先載入(``image_work`` / ``video_work`` 於模組層
import ``FrameAnalysis``,而 ``frame_analysis`` 反向依賴採函式內延遲 import 化解循環)。
"""
# frame_analysis 必須最先載入,確保 FrameAnalysis 在 image_work/video_work import 它之前已定義
from media_processor.pipeline.work.frame_analysis import FrameAnalysis, get_frame_analysis
from media_processor.pipeline.work.image_work import (
    IMAGE_WORK_KEY,
    ImageWork,
    get_image_work,
)
from media_processor.pipeline.work.video_work import (
    VIDEO_WORK_KEY,
    VideoWork,
    audio_file_ready,
    get_video_work,
)

__all__ = [
    "FrameAnalysis",
    "get_frame_analysis",
    "ImageWork",
    "IMAGE_WORK_KEY",
    "get_image_work",
    "VideoWork",
    "VIDEO_WORK_KEY",
    "get_video_work",
    "audio_file_ready",
]
