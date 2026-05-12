from media_processor.abstract_video_processor import AbstractVideoProcessor
from model.gemini_model_manager import GeminiModelManager
from prompt_manager.task_mode import TaskMode

class ComplexVideoProcessor(AbstractVideoProcessor):
    """
    複雜/重要影片處理策略：
    全感知索引器 (Multimodal Event Indexer)。
    強制燒錄時間碼，並交由原生多模態的 Gemini 進行『視聽同步』分析，
    精確抓取動作與聲音的雙重高潮點。
    """
    def __init__(self):
        super().__init__()
        # 使用強大的雲端多模態大腦 (Gemini 2.5 Flash)
        self.vision_engine = GeminiModelManager()
        
        # 複雜影片需要開啟時間碼燒錄以防時間軸幻覺
        self.requires_timecode = True

    def analyze_visual_semantics(self, raw_file_path: str, tc_file_path: str, duration: float) -> dict:
        
        # 將「燒好時間碼」的長影片完整丟給 Gemini，Gemini 會同時處理畫面與音軌
        vlm_result = self.vision_engine.analyze_media(
            media_input=tc_file_path,            
            media_type="video",               
            mode=TaskMode.TIMECODED_ACTION_INDEX     
        )

        # 後處理：針對 Gemini 拆解出來的「多模態事件」，結合聲音與畫面決定最佳的物理重心
        event_indices = vlm_result.get("multimodal_event_index", [])
        for event in event_indices:
            start_t = float(event.get("start_time", 0.0))
            end_t = float(event.get("end_time", duration))
            
            # 優先使用模型依據「聲音或動作高潮」指派的精確秒數 (key_timestamp)
            key_t = event.get("key_timestamp")
            
            # 防呆機制：若模型沒給，或給的時間超出了這個區段，則退回使用區間中點
            if key_t is None or not (start_t <= float(key_t) <= end_t):
                key_t = start_t + (end_t - start_t) / 2.0
            else:
                key_t = float(key_t)
            
            # 在該視聽高潮秒數，呼叫 U2-Net 進行精準的畫面重心抓取
            # 這樣能保證 9:16 裁切時，不會漏掉說話的人或發生巨響的主體
            event["subject_focus"] = self._get_saliency_at_time(raw_file_path, key_t)

        return {
            "is_dense_indexed": True, 
            "cinematic_critique": vlm_result.get("cinematic_critique", ""), 
            "multimodal_event_index": event_indices,
            # 複雜影片依靠事件區塊解析，不進行單一的技術/美學打分
            "technical_score": None,
            "aesthetic_score": None
        }