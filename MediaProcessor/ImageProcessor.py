from PIL import Image, ExifTags
import pillow_heif
from MediaProcessor.MediaStrategy import MediaStrategy
from QwenModelManager import QwenModelManager # 【引入統一大腦】

pillow_heif.register_heif_opener()

class ImageProcessor(MediaStrategy):
    """
    具體策略：處理靜態照片 (支援 JPG, PNG, HEIC)
    重構：移除 OpenCV 物理算法，全面交由 VLM 進行語意與品質審查。
    """
    def __init__(self):
        super().__init__()
        # 初始化統一視覺大腦
        self.vision_engine = QwenModelManager()

    def _extract_exif_metadata(self, pil_image: Image.Image) -> dict:
        """提取 EXIF 拍攝時間與經緯度 (維持不變)"""
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
            # 使用 PIL 開啟圖片 (支援 Apple HEIC)
            pil_image = Image.open(file_path).convert('RGB')
            
            # 提取底層 GPS 資訊
            exif_data = self._extract_exif_metadata(pil_image)

            # 【核心改動】將圖片交給 Qwen VLM 同時進行內容描述與品質判斷
            vlm_result = self.vision_engine.analyze_media(pil_image, media_type="image")

            # 利用大語言模型的判斷來決定是否為廢片
            if vlm_result.get("is_blurry", False):
                return {
                    "status": "rejected", 
                    "reason": "VLM judged as too blurry or out of focus", 
                    "file": file_path,
                    "vlm_caption": vlm_result.get("caption") # 記錄被拒絕的原因
                }

            return {
                "status": "success",
                "type": "image",
                "file": file_path,
                "metadata": {
                    "caption": vlm_result.get("caption"),
                    "creation_time": exif_data.get("datetime"),
                    "location_gps": exif_data.get("gps_info")
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}