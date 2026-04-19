import os
import cv2
from MediaProcessor.MediaStrategy import MediaStrategy
from MediaProcessor.ImageProcessor import ImageProcessor
from MediaProcessor.ShortVideoProcessor import ShortVideoProcessor
from MediaProcessor.LongVideoProcessor import LongVideoProcessor

class MediaProcessorFactory:
    """動態路由：依據 15 秒閾值分發給 Qwen 或 Gemini"""
    
    @staticmethod
    def create_processor(file_path: str) -> MediaStrategy:
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif']:
            return ImageProcessor()
            
        elif ext in ['.mp4', '.mov']:
            duration = MediaProcessorFactory._get_video_duration(file_path)
            
            # 動態路由：15 秒分水嶺
            if duration > 15.0:
                print(f"[Router] 長影片 ({duration:.1f}s) -> 路由至 LongVideoProcessor (Gemini API)")
                return LongVideoProcessor()
            else:
                print(f"[Router] 短影片 ({duration:.1f}s) -> 路由至 ShortVideoProcessor (Local Qwen)")
                return ShortVideoProcessor()
        else:
            raise ValueError(f"不支援的檔案格式: {ext}")

    @staticmethod
    def _get_video_duration(file_path: str) -> float:
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened(): return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return float(frame_count) / float(fps) if fps > 0 else 0.0