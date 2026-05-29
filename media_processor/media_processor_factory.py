"""媒體處理器工廠，依檔案格式與策略動態路由至對應的處理器。"""

import os
from media_processor.media_strategy import MediaStrategy
from media_processor.image_strategy import ImageStrategy
from media_processor.video_strategy import VideoStrategy
from media_processor.image_processor import ImageProcessor
from media_processor.complex_image_processor import ComplexImageProcessor
from media_processor.video_processor import VideoProcessor
from media_processor.complex_video_processor import ComplexVideoProcessor


class MediaProcessorFactory:
    """
    工廠模式 (Factory Method)：依據檔案副檔名與策略動態建立處理器。
    圖片（JPG/PNG/HEIC）→ ImageStrategy 路由；
    影片（MP4/MOV）→ VideoStrategy 路由。
    """

    @staticmethod
    def create_processor(
        file_path: str,
        video_strategy: VideoStrategy = VideoStrategy.SIMPLE,
        image_strategy: ImageStrategy = ImageStrategy.SIMPLE,
    ) -> MediaStrategy:
        """
        根據檔案類型與處理策略建立對應的 MediaStrategy 實例。

        Args:
            file_path:      媒體檔案路徑，副檔名決定處理器類型。
            video_strategy: 影片策略，SIMPLE 使用本地 Qwen，COMPLEX 使用 Gemini API。
            image_strategy: 圖片策略，SIMPLE 使用本地 Qwen，COMPLEX 使用 Gemini API（付費）。

        Returns:
            適當的 MediaStrategy 子類別實例。

        Raises:
            ValueError: 不支援的檔案格式。
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif']:
            if image_strategy == ImageStrategy.COMPLEX:
                print(f"[Router] 深度圖片分析 -> 路由至 ComplexImageProcessor (Gemini API)")
                return ComplexImageProcessor()
            else:
                print(f"[Router] 一般圖片 -> 路由至 ImageProcessor (Local Qwen 全局分析)")
                return ImageProcessor()

        elif ext in ['.mp4', '.mov']:
            if video_strategy == VideoStrategy.COMPLEX:
                print(f"[Router] 複雜/重要影片 -> 路由至 ComplexVideoProcessor (Gemini API 影格索引)")
                return ComplexVideoProcessor()
            else:
                print(f"[Router] 一般影片 -> 路由至 VideoProcessor (Local Qwen 全局分析)")
                return VideoProcessor()
        else:
            raise ValueError(f"不支援的檔案格式: {ext}")
