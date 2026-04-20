from MediaProcessor.AbstractVideoProcessor import AbstractVideoProcessor
from Model.GeminiModelManager import GeminiModelManager
from PromptManager.TaskMode import TaskMode

class ComplexVideoProcessor(AbstractVideoProcessor):
    """
    複雜/重要影片處理策略：
    適用於複雜、動作多且高度依賴時間軸的影片。
    強制燒錄時間碼，並交由 Gemini 進行精確的 TIMECODED_ACTION_INDEX 分析。
    """
    def __init__(self):
        super().__init__()
        self.vision_engine = GeminiModelManager()
        
        # 複雜影片需要開啟時間碼燒錄以防幻覺
        self.requires_timecode = True

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
            "is_dense_indexed": True, 
            "cinematic_critique": vlm_result.get("cinematic_critique"), 
            "action_index": action_indices,
            "technical_score": None,
            "aesthetic_score": None
        }