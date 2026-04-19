import cv2
from PIL import Image
from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.QwenModelManager import QwenModelManager          
from Model.MusiqModelManager import MusiqModelManager
from Model.LaionModelManager import LaionModelManager
from PromptManager.TaskMode import TaskMode

class ShortVideoProcessor(AbstractVideoProcessor):
    """
    短影片處理策略 (<=15s)：
    使用本地端 Qwen2-VL 讀取時間碼影片，輸出帶有時間的 action_index。
    """
    def __init__(self):
        super().__init__()
        self.vision_engine = QwenModelManager()
        self.tech_engine = MusiqModelManager()   
        self.aes_engine = LaionModelManager()    

    def analyze_visual_semantics(self, raw_file_path: str, tc_file_path: str, duration: float) -> dict:
        # 1. 物理畫質打分 (從原片抽中間幀)
        cap = cv2.VideoCapture(raw_file_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, (duration / 2) * 1000)
        ret, frame = cap.read()
        cap.release()

        tech_score, aes_score = 0.0, 0.0
        if ret:
            pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)

        # 2. 語意與時間解析：傳入「燒好時間碼」的影片，呼叫 TIMECODED_ACTION_INDEX
        vlm_result = self.vision_engine.analyze_media(
            media_input=tc_file_path,            
            media_type="video",               
            mode=TaskMode.TIMECODED_ACTION_INDEX     
        )

        # 3. 後處理：為模型回傳的每一個 Action 區間計算物理重心
        action_indices = vlm_result.get("action_index", [])
        for action in action_indices:
            # 抓取該動作區段的中間時間點計算重心
            start_t = action.get("start_time", 0.0)
            end_t = action.get("end_time", duration)
            mid_t = start_t + (end_t - start_t) / 2.0
            action["subject_focus"] = self._get_saliency_at_time(raw_file_path, mid_t)

        return {
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "action_index": action_indices,
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2)
        }