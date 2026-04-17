import numpy as np  # [Bug Fix] 補上 numpy 匯入
import cv2
from PIL import Image, ExifTags
import pillow_heif
from MediaProcessor.MediaStrategy import MediaStrategy

pillow_heif.register_heif_opener()

class ImageProcessor(MediaStrategy):
    """
    具體策略：處理靜態照片 (支援 JPG, PNG, HEIC)
    新增：EXIF 拍攝時間與地點 (GPS) 提取
    """
    def _extract_exif_metadata(self, pil_image: Image.Image) -> dict:
        """
        封裝的內部方法：用於提取照片的拍攝時間與經緯度。
        例如 2026 年初在曼谷或釜山拍攝的照片，通常會帶有這些隱藏標籤。
        """
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
                    metadata["gps_info"] = str(gps_data) # 轉字串避免 JSON 序列化失敗
        except Exception:
            pass # 避免因為某些破壞的 EXIF 導致整張照片解析失敗
            
        return metadata

    def process(self, file_path: str) -> dict:
        try:
            # 1. 讀取影像與基礎轉換
            pil_image = Image.open(file_path).convert('RGB')
            cv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            # 2. 模糊偵測 (Laplacian 變異數)
            blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
            if blur_score < 100: 
                return {"status": "rejected", "reason": "too blurry", "file": file_path}

            # 3. 提取 EXIF 資訊 (時間、地點)
            exif_data = self._extract_exif_metadata(pil_image)

            # 4. 語意描述 (看圖說故事)
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