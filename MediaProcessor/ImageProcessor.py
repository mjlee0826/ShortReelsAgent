from PIL import Image, ExifTags
import pillow_heif
import cv2
import numpy as np

from MediaProcessor.MediaStrategy import MediaStrategy
from Model.QwenModelManager import QwenModelManager
from Model.SaliencyModelManager import SaliencyModelManager
# 【替換】匯入拆分後的雙打分大腦
from Model.MusiqModelManager import MusiqModelManager
from Model.LaionModelManager import LaionModelManager
from PromptManager.TaskMode import TaskMode


pillow_heif.register_heif_opener()

class ImageProcessor(MediaStrategy):
    """
    具體策略：處理靜態照片 (支援 JPG, PNG, HEIC)
    重構：引入 PyIQA (硬體指標) 與 LAION Aesthetic (美學指標) 雙重過濾機制。
    """
    def __init__(self):
        super().__init__()
        # 依賴注入四顆大腦
        self.vision_engine = QwenModelManager()
        self.saliency_engine = SaliencyModelManager()
        self.tech_engine = MusiqModelManager()
        self.aes_engine = LaionModelManager()

    def _extract_exif_metadata(self, pil_image: Image.Image) -> dict:
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
            
            # 1. 計算主體重心 (Saliency U2-Net)
            mask = self.saliency_engine.get_saliency_mask(pil_image)
            M = cv2.moments(mask)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                subject_focus = {"x": int(cx / width * 100), "y": int(cy / height * 100)}
            else:
                subject_focus = {"x": 50, "y": 50} 

            # 2. 【核心改動】雙重評分機制
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)
            
            # 如果技術畫質太差 (例如嚴重的動態模糊、失焦)，直接在前端淘汰
            # 閾值可依據 MANIQA 的實際表現微調 (此處設為 40 分)
            if tech_score < 40.0:
                return {
                    "status": "rejected", 
                    "reason": f"Technical Score too low (Blur/Noise): {tech_score:.1f}", 
                    "file": file_path
                }

            # 3. 呼叫大腦 B (Qwen) 給出攝影評語與描述
            exif_data = self._extract_exif_metadata(pil_image)
            vlm_result = self.vision_engine.analyze_media(pil_image, media_type=TaskMode.GLOBAL_ANALYSIS)

            return {
                "status": "success",
                "type": "image",
                "file": file_path,
                "metadata": {
                    "width": width,             
                    "height": height,           
                    "aspect_ratio": aspect_ratio, 
                    "caption": vlm_result.get("caption"),
                    "cinematic_critique": vlm_result.get("cinematic_critique"), 
                    "technical_score": round(tech_score, 2), # 畫質分數 (精準度至小數點後兩位)
                    "aesthetic_score": round(aes_score, 2),  # 美感分數
                    "subject_focus": subject_focus, 
                    "creation_time": exif_data.get("datetime"),
                    "location_gps": exif_data.get("gps_info")
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}