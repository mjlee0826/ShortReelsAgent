import cv2
import numpy as np
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
    
    技術實作：
    1. 聽覺與基礎流水線：繼承自 AbstractVideoProcessor。
    2. 物理畫質評估：抽取中間幀，使用 MUSIQ 與 LAION 模型進行技術與美學打分。
    3. 語意與影評：直接將「影片路徑」交給 Qwen2-VL，進行全局的運鏡與敘事分析。
    """
    
    def __init__(self):
        super().__init__()
        # 初始化視覺感知大腦
        self.vision_engine = QwenModelManager()
        self.saliency_engine = SaliencyModelManager() 
        self.tech_engine = MusiqModelManager()   
        self.aes_engine = LaionModelManager()    

    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        """
        實作視覺語意分析：
        - 針對物理打分：使用中間幀以節省運算資源。
        - 針對影評描述：使用整段影片以獲取動態資訊。
        """
        cap = cv2.VideoCapture(file_path)
        # 抽取中間幀作為物理指標代表
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration / 2) * 1000)
        ret, frame = cap.read()
        cap.release()

        tech_score = 0.0
        aes_score = 0.0
        subject_focus = None
        
        # 1. 處理物理指標 (必須使用 PIL Image)
        if ret:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            
            # 取得技術畫質與美學分數
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)
            
            # 計算畫面主體的重心座標
            subject_focus = self._calculate_saliency_focus(pil_image)

        # 2. 處理語意指標 (聽從建議，直接給 Qwen 完整的影片檔案路徑)
        # 這樣 Qwen 才能看懂這 15 秒內的運鏡變化
        vlm_result = self.vision_engine.analyze_media(
            media_input=file_path,            # 傳入影片路徑
            media_type="video",               # 正確指定為 video
            mode=TaskMode.GLOBAL_ANALYSIS     # 指定為全局分析模式
        )

        return {
            "visual_caption": vlm_result.get("caption"),
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2),
            "subject_focus": subject_focus
        }

    def _calculate_saliency_focus(self, pil_image: Image.Image) -> dict:
        """
        使用 U2-Net 遮罩計算主體重心的百分比座標。
        這能協助 Phase 4 進行 9:16 的無損裁切。
        """
        try:
            mask = self.saliency_engine.get_saliency_mask(pil_image)
            M = cv2.moments(mask)
            if M["m00"] != 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                width, height = pil_image.size
                return {
                    "x_percent": round((cX / width) * 100, 1),
                    "y_percent": round((cY / height) * 100, 1)
                }
        except Exception as e:
            print(f"[Saliency Calculation Error]: {e}")
            
        return {"x_percent": 50.0, "y_percent": 50.0}