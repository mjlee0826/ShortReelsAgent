import cv2
from PIL import Image
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
# 【切換】從原本的 Qwen 換成 Llava-OneVision
from Model.LlavaOneVisionModelManager import LlavaOneVisionModelManager          
from Model.MusiqModelManager import MusiqModelManager
from Model.LaionModelManager import LaionModelManager
from PromptManager.TaskMode import TaskMode

class ShortVideoProcessor(AbstractVideoProcessor):
    """
    短影片處理策略 (<=15s)：
    採用 LLaVA-OneVision 讀取視覺時間碼影片，
    利用其更強的時序動態理解能力來產出 action_index。
    """
    
    def __init__(self):
        super().__init__()
        # 初始化視覺感知大腦 (切換為 LLaVA)
        self.vision_engine = LlavaOneVisionModelManager()
        self.tech_engine = MusiqModelManager()   
        self.aes_engine = LaionModelManager()    

    def analyze_visual_semantics(self, raw_file_path: str, tc_file_path: str, duration: float) -> dict:
        """
        實作視覺語意分析：
        - 針對物理打分：使用原始影片的中間幀。
        - 針對時間碼分析：將燒好時間碼的影片交給 LLaVA-OneVision。
        """
        # 1. 物理指標評估 (抽取中間幀)
        cap = cv2.VideoCapture(raw_file_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration / 2) * 1000)
        ret, frame = cap.read()
        cap.release()

        tech_score, aes_score = 0.0, 0.0
        if ret:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)

        # 2. 語意與動作索引 (使用帶有時間碼的影片)
        # Llava-OneVision 會在 analyze_media 內部自動進行影格抽取與分析
        vlm_result = self.vision_engine.analyze_media(
            media_input=tc_file_path,            
            media_type="video",               
            mode=TaskMode.TIMECODED_ACTION_INDEX     
        )

        # 3. 重心偵測與後處理
        # 為 LLaVA 辨識出的每一個動作段落補上重心資訊
        action_indices = vlm_result.get("action_index", [])
        for action in action_indices:
            start_t = float(action.get("start_time", 0.0))
            end_t = float(action.get("end_time", duration))
            mid_t = start_t + (end_t - start_t) / 2.0
            # 呼叫 AbstractVideoProcessor 提供的重心計算邏輯
            action["subject_focus"] = self._get_saliency_at_time(raw_file_path, mid_t)

        return {
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "action_index": action_indices,
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2)
        }