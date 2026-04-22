import os
import cv2
from MediaProcessor.MediaStrategy import MediaStrategy
from MediaProcessor.ImageProcessor import ImageProcessor
from MediaProcessor.VideoProcessor import VideoProcessor
from MediaProcessor.ComplexVideoProcessor import ComplexVideoProcessor

class MediaProcessorFactory:
    """
    動態路由：
    依據素材的『複雜度、是否仰賴時間軸、重要性』(is_complex) 來分發，
    而不再單純以影片長度作為判斷標準。
    """
    
    @staticmethod
    def create_processor(file_path: str, is_complex: bool = False) -> MediaStrategy:
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext in ['.jpg', '.jpeg', '.png', '.heic', '.heif']:
            return ImageProcessor()
            
        elif ext in ['.mp4', '.mov']:
            # 動態路由：由 User/系統 決定的複雜度指標
            if is_complex:
                print(f"[Router] 複雜/重要影片 -> 路由至 ComplexVideoProcessor (Gemini API 影格索引)")
                return ComplexVideoProcessor()
            else:
                print(f"[Router] 一般影片 -> 路由至 VideoProcessor (Local Qwen 全局分析)")
                return VideoProcessor()
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