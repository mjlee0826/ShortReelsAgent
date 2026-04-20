import cv2
from PIL import Image
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.QwenModelManager import QwenModelManager          
from Model.MusiqModelManager import MusiqModelManager
from Model.LaionModelManager import LaionModelManager
from PromptManager.TaskMode import TaskMode

class VideoProcessor(AbstractVideoProcessor):
    """
    一般影片處理策略：
    適用於較簡單、不需精細動作時間軸對齊的影片。
    直接將整段影片送入本地端 Qwen 進行全局理解 (GLOBAL_ANALYSIS)。
    """
    def __init__(self):
        super().__init__()
        self.vision_engine = QwenModelManager()
        self.tech_engine = MusiqModelManager()   
        self.aes_engine = LaionModelManager()
        
        # 關閉時間碼燒錄以節省效能
        self.requires_timecode = False

    def analyze_visual_semantics(self, raw_file_path: str, tc_file_path: str, duration: float) -> dict:
        # 1. 物理畫質打分 (從原片抽中間幀)
        cap = cv2.VideoCapture(raw_file_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration / 2) * 1000)
        ret, frame = cap.read()
        cap.release()

        tech_score, aes_score = 0.0, 0.0
        subject_focus = {"x_percent": 50.0, "y_percent": 50.0}
        
        if ret:
            pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)
            # 取得單一全局重心
            subject_focus = self._get_saliency_at_time(raw_file_path, duration / 2.0)

        # 2. 語意解析：不切分，直接傳入原影片，使用 GLOBAL_ANALYSIS 模式
        vlm_result = self.vision_engine.analyze_media(
            media_input=raw_file_path,            
            media_type="video",               
            mode=TaskMode.GLOBAL_ANALYSIS     
        )

        return {
            "caption": vlm_result.get("caption"),
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2),
            "subject_focus": subject_focus
        }