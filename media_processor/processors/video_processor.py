"""一般影片處理器，使用本地 Qwen 進行全局語意分析。"""

from media_processor.processors.abstract_video_processor import AbstractVideoProcessor
from prompt_manager.task_mode import TaskMode


class VideoProcessor(AbstractVideoProcessor):
    """
    具體策略 (Concrete Strategy)：一般影片的感知處理器。
    適用於不需要精細動作時間軸對齊的影片（如 B-roll、景色、短片段）。
    直接將整段影片送入本地端 Qwen 進行全局理解（BASIC_MEDIA_ANALYSIS），
    並以聯集 bbox 策略（頭/中/尾三幀）確保 9:16 裁切不截斷主體。
    tech_engine / aes_engine / mediapipe_engine 繼承自 AbstractVideoProcessor 的 lazy property。
    """

    def __init__(self):
        super().__init__()
        from model.managers.qwen_model_manager import QwenModelManager
        # 主視覺語意引擎（非延遲：為此類的核心差異點）
        self.vision_engine = QwenModelManager()
        # 不需燒錄時間碼，節省處理效能
        self.requires_timecode = False

    def analyze_visual_semantics(
        self,
        raw_file_path: str,
        tc_file_path: str,
        duration: float,
        video_meta: dict,
    ) -> dict:
        """
        視覺語意分析（Hook Method 實作）。
        從影片中間幀計算畫質/視覺特徵，以三幀聯集計算 subject_bbox，
        再以 Qwen 進行全局語意描述。
        """
        # 中間幀：畫質評分 + 視覺特徵包（一次 VideoCapture）
        pil_mid = self._extract_middle_frame_pil(raw_file_path, duration)

        tech_score, aes_score = 0.0, 0.0
        brightness, color_temperature, dominant_colors = 0.0, "", []
        face_info = None

        if pil_mid is not None:
            tech_score = self.tech_engine.get_technical_score(pil_mid)
            aes_score = self.aes_engine.get_aesthetic_score(pil_mid)
            brightness, color_temperature, dominant_colors, face_info = (
                self._compute_frame_features(pil_mid)
            )

        # 三幀聯集 bbox（頭/中/尾），確保主體在整段影片中不被裁切
        subject_bbox = self._get_saliency_bbox_union(raw_file_path, duration)

        # 動態強度（取樣多幀 frame diff）
        motion_intensity = self._compute_motion_intensity(raw_file_path)

        # aspect_ratio 已由 _extract_video_metadata 計算，直接取用
        aspect_ratio = video_meta["aspect_ratio"]
        crop_feasibility = self._compute_crop_feasibility(subject_bbox, aspect_ratio)

        # Qwen 全局語意分析：不切分，直接傳入整段原始影片
        vlm_result = self.vision_engine.analyze_media(
            media_input=raw_file_path,
            media_type="video",
            mode=TaskMode.BASIC_MEDIA_ANALYSIS,
        )

        return {
            "caption": vlm_result.get("caption"),
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
            "motion_intensity": motion_intensity,
            "subject_bbox": subject_bbox,
            "crop_feasibility": crop_feasibility,
            "faces": face_info,
        }
