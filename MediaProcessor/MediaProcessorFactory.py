from MediaProcessor.MediaStrategy import MediaStrategy
from MediaProcessor.ImageProcessor import ImageProcessor
from MediaProcessor.VideoProcessor import VideoProcessor
import os

class MediaProcessorFactory:
    """
    工廠模式 (Factory): 根據副檔名分發對應的處理器
    """
    @staticmethod
    def create_processor(file_path: str) -> MediaStrategy:
        ext = os.path.splitext(file_path)[1].lower()
        # 支援 Apple 專有格式與常見格式
        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif']:
            return ImageProcessor()
        elif ext in ['.mp4', '.mov']: # iPhone 預設錄影多為 mov (內含 H.264 或 HEVC)
            return VideoProcessor()
        else:
            raise ValueError(f"Unsupported file type: {ext}")