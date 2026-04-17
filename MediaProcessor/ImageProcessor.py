import numpy as np
import cv2
from PIL import Image, ExifTags
import pillow_heif
from MediaProcessor.MediaStrategy import MediaStrategy
from BlipModelManager import BlipModelManager # 引入圖片大腦

pillow_heif.register_heif_opener()

class ImageProcessor(MediaStrategy):
    """
    具體策略：處理靜態照片 (支援 JPG, PNG, HEIC)
    """
    def __init__(self):
        super().__init__()
        # 在具體策略中初始化專屬的 AI 模型 (單例模式，不會重複載入)
        self.vision_engine = BlipModelManager()

    def _extract_exif_metadata(self, pil_image: Image.Image) -> dict:
        metadata = {"datetime": None, "gps_info": None}
        try:
            exif = pil_image._getexif()
            if not exif:
                return metadata

            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag == "DateTimeOriginal":
                    metadata["datetime"] = value
                elif tag == "GPSInfo":
                    gps_data = {}
                    for t in value:
                        sub_tag = ExifTags.GPSTAGS.get(t, t)
                        gps_data[sub_tag] = value[t]
                    metadata["gps_info"] = str(gps_data)
        except Exception:
            pass
            
        return metadata

    def process(self, file_path: str) -> dict:
        try:
            pil_image = Image.open(file_path).convert('RGB')
            cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
            if blur_score < 30: 
                return {"status": "rejected", "reason": f'too blurry, blur score = {blur_score}', "file": file_path}

            exif_data = self._extract_exif_metadata(pil_image)
            caption = self.vision_engine.generate_caption(pil_image)

            return {
                "status": "success",
                "type": "image",
                "file": file_path,
                "metadata": {
                    "caption": caption,
                    "blur_score": blur_score,
                    "creation_time": exif_data.get("datetime"),
                    "location_gps": exif_data.get("gps_info")
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}