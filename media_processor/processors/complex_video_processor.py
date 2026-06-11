"""複雜影片處理器，使用 Gemini API 進行精確的多模態事件索引。"""

from media_processor.processors.abstract_video_processor import AbstractVideoProcessor
from model.managers.gemini_model_manager import GeminiModelManager
from prompt_manager.task_mode import TaskMode


class ComplexVideoProcessor(AbstractVideoProcessor):
    """
    具體策略 (Concrete Strategy)：複雜/重要影片的全感知索引器。
    強制燒錄視覺時間碼，將影片完整上傳至 Gemini，進行「視聽同步」精確分析，
    產出以時間區段為單位的 multimodal_event_index，精準抓取動作與聲音的雙重高潮點。
    適用於主要表演片段、重要訪談、或需要精細剪輯點的素材。
    """

    def __init__(self):
        super().__init__()
        # 使用雲端多模態大腦（Gemini Flash）進行視聽同步分析
        self.vision_engine = GeminiModelManager()
        # 必須燒錄時間碼，防止 Gemini 產生時間軸幻覺
        self.requires_timecode = True

    def analyze_visual_semantics(
        self,
        raw_file_path: str,
        tc_file_path: str,
        duration: float,
        video_meta: dict,
    ) -> dict:
        """
        視覺語意分析（Hook Method 實作）。
        將燒有時間碼的影片送入 Gemini，解析出多模態事件清單與全局語意標籤，
        再對每個事件的視聽高潮點呼叫 U2-Net + MediaPipe 計算精準畫面 bbox。
        """
        # 燒好時間碼的影片完整送入 Gemini，同時處理畫面與音軌
        vlm_result = self.vision_engine.analyze_media(
            media_input=tc_file_path,
            media_type="video",
            mode=TaskMode.VIDEO_EVENT_INDEX,
        )

        # 後處理：為每個多模態事件計算最佳畫面 bbox
        event_indices = vlm_result.get("multimodal_event_index", [])
        for event in event_indices:
            start_t = float(event.get("start_time", 0.0))
            end_t = float(event.get("end_time", duration))

            # 優先採用模型依據「聲音或動作高潮」指定的精確秒數
            key_t = event.get("key_timestamp")
            if key_t is None or not (start_t <= float(key_t) <= end_t):
                # 防呆：模型未提供或超出區段範圍，退回使用區間中點
                key_t = start_t + (end_t - start_t) / 2.0
            else:
                key_t = float(key_t)

            # 在視聽高潮秒數呼叫 U2-Net + MediaPipe，確保 9:16 裁切時主體不被截切
            bbox = self._get_saliency_at_time(raw_file_path, key_t)
            event["subject_bbox"] = bbox.model_dump()

        # 從中間幀計算全局視覺特徵 + 畫質/美學分數（一次 VideoCapture）
        tech_score, aes_score = 0.0, 0.0
        brightness, color_temperature, dominant_colors = 0.0, "", []
        face_info = None
        pil_mid = self._extract_middle_frame_pil(raw_file_path, duration)
        if pil_mid is not None:
            # 代表幀畫質（MUSIQ）+ 美學（LAION）評分，與 Simple/Image 一致供導演選材
            tech_score = self.tech_engine.get_technical_score(pil_mid)
            aes_score = self.aes_engine.get_aesthetic_score(pil_mid)
            brightness, color_temperature, dominant_colors, face_info = (
                self._compute_frame_features(pil_mid)
            )

        # 複雜影片仍以事件區塊為主，但保留代表幀畫質/美學分供導演端寬容過濾與選材
        return {
            "is_dense_indexed": True,
            "cinematic_critique": vlm_result.get("cinematic_critique", ""),
            "mood": vlm_result.get("mood", ""),
            "scene_tags": vlm_result.get("scene_tags", []),
            "camera_angle": vlm_result.get("camera_angle", ""),
            "action_tags": vlm_result.get("action_tags", []),
            "time_of_day": vlm_result.get("time_of_day", ""),
            "technical_score": round(tech_score, 2),
            "aesthetic_score": round(aes_score, 2),
            "brightness": brightness,
            "color_temperature": color_temperature,
            "dominant_colors": dominant_colors,
            "faces": face_info,
            "multimodal_event_index": event_indices,
        }
