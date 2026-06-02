"""
media_processor.processors 套件:策略型媒體處理器 (Strategy + Factory Pattern)。

把「整段 process() 一次跑完」的 MediaStrategy 具體實作集中於此,與 pipeline/ 的細粒度
Stage 編排分層。對外公開:
- ``MediaProcessorFactory`` — 依副檔名與策略路由至對應 processor (Factory Method)
- 圖片 / 影片的抽象基底與 Simple / Complex 具體策略
共用契約 (``models``) 與基底介面 (``media_strategy``) 仍留在 media_processor 根目錄。
"""
from media_processor.processors.abstract_image_processor import AbstractImageProcessor
from media_processor.processors.abstract_video_processor import AbstractVideoProcessor
from media_processor.processors.complex_image_processor import ComplexImageProcessor
from media_processor.processors.complex_video_processor import ComplexVideoProcessor
from media_processor.processors.image_processor import ImageProcessor
from media_processor.processors.media_processor_factory import MediaProcessorFactory
from media_processor.processors.video_processor import VideoProcessor

__all__ = [
    "MediaProcessorFactory",
    "AbstractImageProcessor",
    "AbstractVideoProcessor",
    "ImageProcessor",
    "ComplexImageProcessor",
    "VideoProcessor",
    "ComplexVideoProcessor",
]
