"""抽象影片處理器，定義影片感知分析的通用流水線。"""

import os
import cv2
import tempfile
import gc
import torch
from PIL import Image
from abc import abstractmethod

from media_processor.media_strategy import MediaStrategy
from media_processor.models import ProcessorResult, SubjectBbox, FaceInfo
from media_tools.ffmpeg_adapter import FFmpegAdapter
from template_engine.scene_cut_extractor import SceneCutExtractor
from config.media_processor_config import (
    MINIMUM_AUDIO_FILE_BYTES,
    SALIENCY_SAMPLE_POSITIONS,
    MIDDLE_FRAME_POSITION,
)


class AbstractVideoProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method) + 延遲載入模式 (Lazy Initialization)：
    定義影片處理的三階段流水線（時間碼燒錄 → 音訊分析 → 視覺語意分析），
    由子類別實作 analyze_visual_semantics() 注入差異化的視覺感知邏輯。
    各 AI 模型引擎透過 @property 延遲載入，VRAM 只在真正使用時才佔用。
    """

    def __init__(self):
        super().__init__()
        # 延遲載入的引擎實例（透過 @property 按需初始化）
        self._whisper_engine = None
        self._audio_env_engine = None
        self._vad_engine = None
        self._saliency_engine = None
        self._mediapipe_engine = None
        self._tech_engine = None
        self._aes_engine = None

        self._ffmpeg = FFmpegAdapter()
        # 子類別可覆寫：ComplexVideoProcessor 設為 True 以啟用時間碼燒錄
        self.requires_timecode = False

    # ── 延遲載入引擎 (Lazy Initialization) ───────────────────────────────────

    @property
    def whisper_engine(self):
        """語音轉文字引擎（首次存取時載入至 GPU）。"""
        if self._whisper_engine is None:
            from model.managers.whisper_model_manager import WhisperModelManager
            self._whisper_engine = WhisperModelManager()
        return self._whisper_engine

    @property
    def audio_env_engine(self):
        """環境音分類引擎（首次存取時載入至 GPU）。"""
        if self._audio_env_engine is None:
            from model.managers.audio_env_model_manager import AudioEnvModelManager
            self._audio_env_engine = AudioEnvModelManager()
        return self._audio_env_engine

    @property
    def vad_engine(self):
        """語音活動偵測引擎（首次存取時載入至 GPU）。"""
        if self._vad_engine is None:
            from model.managers.vad_model_manager import VadModelManager
            self._vad_engine = VadModelManager()
        return self._vad_engine

    @property
    def saliency_engine(self):
        """顯著性偵測引擎 U2-Net（首次存取時載入至 GPU）。"""
        if self._saliency_engine is None:
            from model.managers.saliency_model_manager import SaliencyModelManager
            self._saliency_engine = SaliencyModelManager()
        return self._saliency_engine

    @property
    def mediapipe_engine(self):
        """MediaPipe 臉部偵測引擎（首次存取時初始化）。"""
        if self._mediapipe_engine is None:
            from model.managers.mediapipe_model_manager import MediaPipeModelManager
            self._mediapipe_engine = MediaPipeModelManager()
        return self._mediapipe_engine

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

    # ── Template Method 主流程 ────────────────────────────────────────────────

    def process(self, file_path: str) -> dict:
        """
        影片感知分析主流程（Template Method）。
        依序：GPU 清理 → 影片元數據擷取 → 時間碼燒錄（選用）→ 音訊分析 →
        場景切換點擷取 → 視覺語意分析。
        回傳與 ProcessorResult.to_dict() 相容的 dict。
        """
        temp_audio_path = None
        temp_tc_video_path = None

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

        try:
            video_meta = self._extract_video_metadata(file_path)

            # 燒錄時間碼（僅 ComplexVideoProcessor 需要）
            if self.requires_timecode:
                temp_tc_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
                temp_tc_video_path = temp_tc_video.name
                temp_tc_video.close()
                self._ffmpeg.burn_timecode(file_path, temp_tc_video_path)
            else:
                temp_tc_video_path = file_path

            # 音訊分析
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio_path = temp_audio.name
            temp_audio.close()
            self._ffmpeg.extract_ai_audio(file_path, temp_audio_path)

            audio_transcript, env_sounds, has_speech, spoken_language = self._analyze_audio(temp_audio_path)

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

            # 場景切換點擷取（CPU，不需 GPU）
            scene_cuts = self._extract_scene_cuts(file_path)

            # 視覺語意分析（由子類別實作）
            visual_metadata = self.analyze_visual_semantics(
                file_path, temp_tc_video_path, video_meta["duration"], video_meta
            )

            return ProcessorResult(
                status="success",
                type="video",
                file=file_path,
                metadata={
                    **video_meta,
                    "has_speech": has_speech,
                    "spoken_language": spoken_language,
                    "audio_transcript": audio_transcript,
                    "environmental_sounds": env_sounds,
                    "scene_cuts": scene_cuts,
                    **visual_metadata,
                },
            ).to_dict()

        except Exception as e:
            # asset 級失敗：同圖片處理器，吞例外回 error dict 前先印出哪支影片、為何失敗
            print(f"[VideoProcessor Error] 處理失敗 {file_path}: {e}")
            return ProcessorResult(
                status="error", file=file_path, message=str(e)
            ).to_dict()

        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass
            if (
                self.requires_timecode
                and temp_tc_video_path
                and temp_tc_video_path != file_path
                and os.path.exists(temp_tc_video_path)
            ):
                try:
                    os.remove(temp_tc_video_path)
                except OSError:
                    pass

    # ── 私有輔助方法 ─────────────────────────────────────────────────────────

    def _extract_video_metadata(self, file_path: str) -> dict:
        """
        擷取影片的基本元數據。
        解析度/FPS/片長以 cv2 讀取；建立時間與 GPS 座標需從容器標籤取得，
        改用 FFmpegAdapter 的 ffprobe 擷取（cv2 無法存取容器層 metadata）。
        """
        cap = cv2.VideoCapture(file_path)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        duration = float(frame_count) / float(fps) if fps > 0 else 0.0
        aspect_ratio = round(width / height, 4) if height > 0 else 0.0

        container_meta = self._ffmpeg.extract_container_metadata(file_path)
        return {
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
            "fps": round(fps, 2),
            "duration": duration,
            "creation_time": container_meta["creation_time"],
            "location_gps": container_meta["location_gps"],
        }

    def _analyze_audio(self, audio_path: str) -> tuple[dict, list, bool, str]:
        """
        執行音訊三階段分析：VAD 偵測語音 → Whisper 轉錄 → 環境音分類。
        若音訊檔過小（靜音影片），直接回傳空結果。
        回傳 (transcript, env_sounds, has_speech, spoken_language)。
        """
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) <= MINIMUM_AUDIO_FILE_BYTES:
            return {}, [], False, ""

        transcript = {}
        has_speech = self.vad_engine.has_speech(audio_path)
        if has_speech:
            transcript = self.whisper_engine.transcribe(audio_path)
        spoken_language = transcript.get("language", "")
        env_sounds = self.audio_env_engine.classify_environment(audio_path)
        return transcript, env_sounds, has_speech, spoken_language

    def _extract_scene_cuts(self, file_path: str) -> list[float]:
        """
        以 SceneCutExtractor 擷取影片中的場景切換時間點列表。
        失敗時靜默回傳空列表，不阻斷主流程。
        """
        try:
            return SceneCutExtractor().get_cuts(file_path)
        except Exception as e:
            # 場景切點失敗不阻斷主流程，但需印出以免靜默吞錯後難以定位
            print(f"[VideoProcessor Warning] 場景切點擷取失敗 {file_path}: {e}")
            return []

    def _get_saliency_at_time(self, file_path: str, time_sec: float) -> SubjectBbox:
        """
        在影片指定時間點抓取幀，計算主體 bbox 百分比座標。
        若偵測到臉部，以臉部 bbox 覆蓋 U2-Net saliency bbox（語意更準確）。
        失敗時退回全畫面安全區域 (0,0,100,100)。
        """
        try:
            cap = cv2.VideoCapture(file_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
            ret, frame = cap.read()
            cap.release()
            if ret:
                pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                width, height = pil_image.size
                # U2-Net saliency bbox
                mask = self.saliency_engine.get_saliency_mask(pil_image)
                bbox = self._compute_saliency_bbox(mask, width, height)
                # 臉部偵測：有臉則以 face bbox 覆蓋
                _, face_bbox = self.mediapipe_engine.detect(pil_image)
                if face_bbox is not None:
                    bbox = face_bbox
                return bbox
        except Exception as e:
            # 抓幀 / 臉部偵測失敗時退回全畫面安全區；印警告協助定位（saliency 本身另有內部 log）
            print(f"[VideoProcessor Warning] saliency 抓幀失敗 (t={time_sec:.1f}s): {e}")
        return SubjectBbox(x1=0.0, y1=0.0, x2=100.0, y2=100.0)

    def _get_saliency_bbox_union(self, file_path: str, duration: float) -> SubjectBbox:
        """
        取頭（10%）/ 中（50%）/ 尾（90%）三幀的 saliency bbox，回傳聯集。
        聯集 bbox 代表整段影片主體曾出現的最大安全區域，確保 9:16 裁切不截斷主體。
        """
        sample_times = [duration * p for p in SALIENCY_SAMPLE_POSITIONS]
        bboxes = [self._get_saliency_at_time(file_path, t) for t in sample_times]
        return self._union_bboxes(bboxes)

    def _extract_middle_frame_pil(
        self, file_path: str, duration: float
    ) -> "Image.Image | None":
        """
        取影片代表幀（MIDDLE_FRAME_POSITION），回傳 PIL Image。
        失敗時回傳 None，不拋例外。
        """
        try:
            cap = cv2.VideoCapture(file_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, duration * MIDDLE_FRAME_POSITION * 1000)
            ret, frame = cap.read()
            cap.release()
            if ret:
                return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        except Exception as e:
            # 取代表幀失敗不致命（下游會跳過畫質 / 視覺特徵），印警告即可
            print(f"[VideoProcessor Warning] 代表幀擷取失敗 {file_path}: {e}")
        return None

    def _compute_frame_features(
        self, pil_image: "Image.Image"
    ) -> "tuple[float, str, list[str], FaceInfo | None]":
        """
        從單幀 PIL Image 計算視覺特徵包：亮度、色溫、主色、臉部資訊。
        回傳 (brightness, color_temperature, dominant_colors, face_info)。
        """
        brightness = self._compute_brightness(pil_image)
        color_temperature = self._compute_color_temperature(pil_image)
        dominant_colors = self._compute_dominant_colors(pil_image)
        face_info, _ = self.mediapipe_engine.detect(pil_image)
        return brightness, color_temperature, dominant_colors, face_info

    # ── 抽象方法（由子類別實作）─────────────────────────────────────────────

    @abstractmethod
    def analyze_visual_semantics(
        self, raw_file_path: str, tc_file_path: str, duration: float, video_meta: dict
    ) -> dict:
        """
        視覺語意分析（Hook Method）。
        VideoProcessor 使用本地 Qwen 全局分析；
        ComplexVideoProcessor 使用 Gemini API 精確時間索引。
        """
        pass
