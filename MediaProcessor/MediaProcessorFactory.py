import os
import cv2
from MediaProcessor.MediaStrategy import MediaStrategy
from MediaProcessor.ImageProcessor import ImageProcessor
from MediaProcessor.StandardVideoProcessor import StandardVideoProcessor
from MediaProcessor.DenseSequenceVideoProcessor import DenseSequenceVideoProcessor

class MediaProcessorFactory:
    """
    工廠模式 (Factory) 與 動態路由 (Dynamic Routing)：
    根據副檔名分發處理器。若為影片，則動態探測時長，
    超過 15 秒的長鏡頭路由至「密集切片處理器」，反之則交給「標準處理器」。
    """
    @staticmethod
    def create_processor(file_path: str) -> MediaStrategy:
        ext = os.path.splitext(file_path)[1].lower()
        
        # 處理靜態圖片
        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif']:
            return ImageProcessor()
            
        # 處理動態影片
        elif ext in ['.mp4', '.mov']:
            duration = MediaProcessorFactory._get_video_duration(file_path)
            
            # 動態路由閾值：15 秒
            if duration > 15.0:
                print(f"[Router] 長影片 ({duration:.1f}s) -> 路由至 DenseSequenceVideoProcessor")
                return DenseSequenceVideoProcessor()
            else:
                print(f"[Router] 短影片 ({duration:.1f}s) -> 路由至 StandardVideoProcessor")
                return StandardVideoProcessor()
        else:
            raise ValueError(f"不支援的檔案格式: {ext}")

    @staticmethod
    def _get_video_duration(file_path: str) -> float:
        """輕量級探測影片時長，避免載入完整影片佔用記憶體"""
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return float(frame_count) / float(fps) if fps > 0 else 0.0