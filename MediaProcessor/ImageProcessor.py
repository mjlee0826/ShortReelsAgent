from PIL import Image, ExifTags
import pillow_heif
from MediaProcessor.MediaStrategy import MediaStrategy
from QwenModelManager import QwenModelManager
from SaliencyModelManager import SaliencyModelManager
import cv2
import numpy as np

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
        self.saliency_engine = SaliencyModelManager()

    def _extract_exif_metadata(self, pil_image: Image.Image) -> dict:
        # ... (維持原樣，略過以省篇幅) ...
        metadata = {"datetime": None, "gps_info": None}
        try:
            exif = pil_image.getexif()
            if not exif:
                return metadata
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag == "DateTime":
                    metadata["datetime"] = str(value)
            exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            if exif_ifd:
                for tag_id, value in exif_ifd.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == "DateTimeOriginal":
                        metadata["datetime"] = str(value)
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if gps_ifd:
                gps_data = {}
                for tag_id, value in gps_ifd.items():
                    tag = ExifTags.GPSTAGS.get(tag_id, tag_id)
                    gps_data[tag] = str(value) 
                if gps_data:
                    metadata["gps_info"] = str(gps_data)
        except Exception:
            pass
        return metadata

    def process(self, file_path: str) -> dict:
        try:
            pil_image = Image.open(file_path).convert('RGB')
            width, height = pil_image.size
            aspect_ratio = round(width / height, 4) if height > 0 else 0
            
            # 【核心邏輯 1】取得顯著性遮罩 (U2-Net Mask)
            mask = self.saliency_engine.get_saliency_mask(pil_image)
            
            # 【核心邏輯 2】計算主體重心 (Center of Mass)
            M = cv2.moments(mask)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                subject_focus = {"x": int(cx / width * 100), "y": int(cy / height * 100)}
            else:
                subject_focus = {"x": 50, "y": 50} # 找不到主體時回歸中心

            # 【核心邏輯 3】Saliency-Masked Laplacian 模糊偵測
            # 只針對 Mask > 128 (顯著區域) 計算模糊度，完美避開背景散景干擾
            gray = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2GRAY)
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            masked_laplacian = laplacian[mask > 128]
            
            # 如果主體區域大於 0 才計算，否則退回全局計算
            blur_score = masked_laplacian.var() if len(masked_laplacian) > 0 else laplacian.var()

            # 嚴格的廢片閾值 (實測建議設為 50~100 之間)
            if blur_score < 50:
                return {
                    "status": "rejected", 
                    "reason": f"Saliency-Masked Blur (score: {blur_score:.1f})", 
                    "file": file_path
                }

            exif_data = self._extract_exif_metadata(pil_image)
            vlm_result = self.vision_engine.analyze_media(pil_image, media_type="image")

            return {
                "status": "success",
                "type": "image",
                "file": file_path,
                "metadata": {
                    "width": width,             
                    "height": height,           
                    "aspect_ratio": aspect_ratio, 
                    "caption": vlm_result.get("caption"),
                    "subject_focus": subject_focus, # 【精準座標】
                    "creation_time": exif_data.get("datetime"),
                    "location_gps": exif_data.get("gps_info")
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}