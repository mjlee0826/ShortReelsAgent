from MediaProcessor.MediaStrategy import MediaStrategy
import cv2
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

class VideoProcessor(MediaStrategy):
    """
    具體策略：處理動態影片 (支援 MP4, MOV, HEVC)
    """
    def process(self, file_path: str) -> dict:
        try:
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return {"status": "error", "file": file_path, "message": "Failed to read video"}

            # 1. 取得影片長度資訊
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            # 2. 抽取中間幀進行語意分析
            middle_frame_idx = int(total_frames / 2)
            cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_idx)
            ret, frame = cap.read()
            
            caption = "No caption generated"
            if ret:
                # 將 OpenCV 的 BGR 格式轉回 PIL 的 RGB 給 BLIP 使用
                pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                caption = self.vision_engine.generate_caption(pil_image)

            cap.release()

            return {
                "status": "success",
                "type": "video",
                "file": file_path,
                "metadata": {
                    "duration": duration,
                    "caption": caption
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}