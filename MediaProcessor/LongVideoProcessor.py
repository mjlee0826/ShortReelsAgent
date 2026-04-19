from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.GeminiModelManager import GeminiModelManager
from PromptManager.TaskMode import TaskMode

class LongVideoProcessor(AbstractVideoProcessor):
    """
    長影片處理策略 (>15s)：
    捨棄物理切片。直接將帶有時間碼的長影片上傳至強大的 Gemini 1.5 Flash API，
    完美保留因果關係並透過 OCR 取得精準 Timestamp。
    """
    def __init__(self):
        super().__init__()
        # 使用強大的雲端大腦
        self.vision_engine = GeminiModelManager()

    def analyze_visual_semantics(self, raw_file_path: str, tc_file_path: str, duration: float) -> dict:
        
        # 將「燒好時間碼」的長影片完整丟給 Gemini
        vlm_result = self.vision_engine.analyze_media(
            media_input=tc_file_path,            
            media_type="video",               
            mode=TaskMode.TIMECODED_ACTION_INDEX     
        )

        # 後處理：為 Gemini 拆解出來的每一個動作區間補上實體重心
        action_indices = vlm_result.get("action_index", [])
        for action in action_indices:
            start_t = float(action.get("start_time", 0.0))
            end_t = float(action.get("end_time", duration))
            mid_t = start_t + (end_t - start_t) / 2.0
            action["subject_focus"] = self._get_saliency_at_time(raw_file_path, mid_t)

        return {
            "is_dense_indexed": True, # 保留此 Flag 供下游辨識
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "action_index": action_indices,
            # 長影片不進行單一技術打分
            "technical_score": None,
            "aesthetic_score": None
        }