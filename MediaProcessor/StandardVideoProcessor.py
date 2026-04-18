import cv2
from PIL import Image
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.QwenModelManager import QwenModelManager          
from Model.SaliencyModelManager import SaliencyModelManager 
from Model.MusiqModelManager import MusiqModelManager
from Model.LaionModelManager import LaionModelManager
from PromptManager.TaskMode import TaskMode

class StandardVideoProcessor(AbstractVideoProcessor):
    """
    具體策略 A：針對 15 秒以下的短影音。
    邏輯：抽取中間幀，進行一次性的技術打分、美學打分，並要求 Qwen 給出全局的攝影評論。
    """
    def __init__(self):
        super().__init__()
        self.vision_engine = QwenModelManager()
        self.saliency_engine = SaliencyModelManager() 
        self.tech_engine = MusiqModelManager()   
        self.aes_engine = LaionModelManager()    

    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        cap = cv2.VideoCapture(file_path)
        # 抽取中間幀作為代表
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration / 2) * 1000)
        ret, frame = cap.read()
        cap.release()

        tech_score = 0.0
        aes_score = 0.0
        subject_focus = None
        vlm_result = {}

        if ret:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            
            # 物理與美學指標運算
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)
            subject_focus = self._calculate_saliency_focus(pil_image)
            
            # Qwen 全局語意與攝影評論 (使用 Cinematic Prompt)
            vlm_result = self.vision_engine.analyze_media(pil_image, media_type=TaskMode.GLOBAL_ANALYSIS)

        return {
            "visual_caption": vlm_result.get("caption"),
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2),
            "subject_focus": subject_focus, 
        }

    def _calculate_saliency_focus(self, pil_image: Image.Image) -> dict:
        # 實作原有的 U2-Net 重心計算邏輯...
        return {"x_percent": 50, "y_percent": 50}