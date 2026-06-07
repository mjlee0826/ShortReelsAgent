"""靜態圖片處理器的抽象基底，定義圖片感知分析的通用流水線。"""

from abc import abstractmethod
from PIL import Image
import pillow_heif

from media_processor.media_strategy import MediaStrategy
from media_processor.models import ProcessorResult, ImageMetadata, SubjectBbox
from config.media_processor_config import TECHNICAL_SCORE_FILTER_THRESHOLD

pillow_heif.register_heif_opener()


class AbstractImageProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method) + 延遲載入模式 (Lazy Initialization)：
    定義靜態圖片感知分析的通用流水線（saliency → 評分 → 視覺特徵 → 臉部 → VLM）。
    由子類別實作 analyze_visual_semantics() 注入差異化的視覺語意分析引擎。
    所有 AI 引擎透過 @property 延遲載入，僅在首次使用時佔用 VRAM。
    """

    def __init__(self):
        super().__init__()
        self._saliency_engine = None
        self._tech_engine = None
        self._aes_engine = None
        self._mediapipe_engine = None

    # ── 延遲載入引擎 (Lazy Initialization) ───────────────────────────────────

    @property
    def saliency_engine(self):
        """U2-Net 顯著性偵測引擎（首次存取時載入至 GPU）。"""
        if self._saliency_engine is None:
            from model.managers.saliency_model_manager import SaliencyModelManager
            self._saliency_engine = SaliencyModelManager()
        return self._saliency_engine

    @property
    def tech_engine(self):
        """MUSIQ 技術畫質評分引擎（首次存取時載入至 GPU）。"""
        if self._tech_engine is None:
            from model.managers.musiq_model_manager import MusiqModelManager
            self._tech_engine = MusiqModelManager()
        return self._tech_engine

    @property
    def aes_engine(self):
        """LAION 美學評分引擎（首次存取時載入至 GPU）。"""
        if self._aes_engine is None:
            from model.managers.laion_model_manager import LaionModelManager
            self._aes_engine = LaionModelManager()
        return self._aes_engine

    @property
    def mediapipe_engine(self):
        """MediaPipe 臉部偵測引擎（首次存取時初始化）。"""
        if self._mediapipe_engine is None:
            from model.managers.mediapipe_model_manager import MediaPipeModelManager
            self._mediapipe_engine = MediaPipeModelManager()
        return self._mediapipe_engine

    # ── Template Method 主流程 ────────────────────────────────────────────────

    def process(self, file_path: str) -> dict:
        """
        圖片感知分析主流程（Template Method）。
        開圖 → saliency bbox → 雙重評分 → 畫質過濾 →
        視覺特徵 → 臉部偵測 → EXIF → analyze_visual_semantics。
        """
        try:
            pil_image = Image.open(file_path).convert("RGB")
            width, height = pil_image.size
            aspect_ratio = round(width / height, 4) if height > 0 else 0.0

            # U2-Net saliency bbox
            mask = self.saliency_engine.get_saliency_mask(pil_image)
            subject_bbox: SubjectBbox = self._compute_saliency_bbox(mask, width, height)

            # 雙重評分：技術畫質（MUSIQ）+ 美學評分（LAION）
            tech_score = self.tech_engine.get_technical_score(pil_image)
            aes_score = self.aes_engine.get_aesthetic_score(pil_image)

            # 技術畫質不足時提前 reject，不進入耗時的 VLM 分析
            if tech_score < TECHNICAL_SCORE_FILTER_THRESHOLD:
                return ProcessorResult(
                    status="rejected",
                    file=file_path,
                    reason=f"Technical Score too low (Blur/Noise): {tech_score:.1f}",
                ).to_dict()

            # 純 cv2/PIL 視覺特徵計算
            brightness = self._compute_brightness(pil_image)
            color_temperature = self._compute_color_temperature(pil_image)
            dominant_colors = self._compute_dominant_colors(pil_image)

            # 臉部偵測：有臉時以 face bbox 覆蓋 saliency bbox
            face_info, face_bbox = self.mediapipe_engine.detect(pil_image)
            if face_bbox is not None:
                subject_bbox = face_bbox

            crop_feasibility = self._compute_crop_feasibility(subject_bbox, aspect_ratio)
            exif_data = self._extract_exif_metadata(pil_image)

            # 子類別注入語意分析引擎（Qwen 或 Gemini）
            vlm_result = self.analyze_visual_semantics(pil_image, exif_data)

            metadata = ImageMetadata(
                width=width,
                height=height,
                aspect_ratio=aspect_ratio,
                creation_time=exif_data.get("datetime", ""),
                location_gps=exif_data.get("gps_info", ""),
                caption=vlm_result.get("caption"),
                cinematic_critique=vlm_result.get("cinematic_critique"),
                mood=vlm_result.get("mood", ""),
                scene_tags=vlm_result.get("scene_tags", []),
                camera_angle=vlm_result.get("camera_angle", ""),
                action_tags=vlm_result.get("action_tags", []),
                time_of_day=vlm_result.get("time_of_day", ""),
                technical_score=round(tech_score, 2),
                aesthetic_score=round(aes_score, 2),
                brightness=brightness,
                color_temperature=color_temperature,
                dominant_colors=dominant_colors,
                subject_bbox=subject_bbox,
                crop_feasibility=crop_feasibility,
                faces=face_info,
            )

            return ProcessorResult(
                status="success",
                type="image",
                file=file_path,
                metadata=metadata,
            ).to_dict()

        except Exception as e:
            # asset 級失敗：process() 自行吞例外只回 error dict，若不在此印出，
            # console 完全看不到是哪張圖、為何失敗（上層 Pipeline 也只會收到 error 狀態）
            print(f"[ImageProcessor Error] 處理失敗 {file_path}: {e}")
            return ProcessorResult(
                status="error", file=file_path, message=str(e)
            ).to_dict()

    # ── 抽象方法（由子類別實作）─────────────────────────────────────────────

    @abstractmethod
    def analyze_visual_semantics(
        self, pil_image: Image.Image, exif_data: dict
    ) -> dict:
        """
        視覺語意分析（Hook Method）。
        ImageProcessor 使用本地 Qwen；ComplexImageProcessor 使用 Gemini API。
        回傳含 caption / mood / scene_tags 等欄位的 dict。
        """
        pass
