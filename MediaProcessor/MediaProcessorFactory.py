import os
from MediaProcessor.MediaStrategy import MediaStrategy
from MediaProcessor.VideoStrategy import VideoStrategy
from MediaProcessor.ImageProcessor import ImageProcessor
from MediaProcessor.VideoProcessor import VideoProcessor
from MediaProcessor.ComplexVideoProcessor import ComplexVideoProcessor

class MediaProcessorFactory:
    """
    動態路由：
    依據 VideoStrategy 決定使用本地 Qwen (SIMPLE) 或 Gemini 精確索引 (COMPLEX)。
    """

    @staticmethod
    def create_processor(file_path: str, strategy: VideoStrategy = VideoStrategy.SIMPLE) -> MediaStrategy:
        ext = os.path.splitext(file_path)[1].lower()

        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif']:
            return ImageProcessor()

        elif ext in ['.mp4', '.mov']:
            if strategy == VideoStrategy.COMPLEX:
                print(f"[Router] 複雜/重要影片 -> 路由至 ComplexVideoProcessor (Gemini API 影格索引)")
                return ComplexVideoProcessor()
            else:
                print(f"[Router] 一般影片 -> 路由至 VideoProcessor (Local Qwen 全局分析)")
                return VideoProcessor()
        else:
            raise ValueError(f"不支援的檔案格式: {ext}")
