import cv2
from PIL import Image
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.QwenModelManager import QwenModelManager          
from Model.MusiqModelManager import MusiqModelManager
from Model.LaionModelManager import LaionModelManager
from PromptManager.TaskMode import TaskMode

class StandardVideoProcessor(AbstractVideoProcessor):
    """具體策略 A：針對 15 秒以下的短影音。"""
    
    def __init__(self):
        super().__init__()
        self.vision_engine = QwenModelManager()
        self.tech_engine = MusiqModelManager()   
        self.aes_engine = LaionModelManager()    

    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        cap = cv2.VideoCapture(file_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration / 2) * 1000)
        ret, frame = cap.read()
        cap.release()

        tech_score = 0.0
        aes_score = 0.0
        subject_focus = {"x_percent": 50.0, "y_percent": 50.0}
        
        if ret:
            pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)
            # 呼叫父類別共通邏輯
            subject_focus = self._calculate_saliency_focus(pil_image)

        vlm_result = self.vision_engine.analyze_media(
            media_input=file_path,            
            media_type="video",               
            mode=TaskMode.GLOBAL_ANALYSIS     
        )

        return {
            "visual_caption": vlm_result.get("caption"),
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2),
            "subject_focus": subject_focus
        }