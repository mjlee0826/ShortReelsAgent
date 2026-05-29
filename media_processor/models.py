"""
媒體處理器輸出的 Pydantic 資料模型 (Value Object Pattern)。
所有 processor 的回傳值先建構這些模型，再透過 .to_dict() 輸出 dict，
確保結構一致且有型別保護，同時對下游 DirectorService 完全向後相容。
"""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


class SubjectBbox(BaseModel):
    """畫面主體必須保留的矩形區域，以百分比座標表示（0–100）。"""
    x1: float
    y1: float
    x2: float
    y2: float


class FaceInfo(BaseModel):
    """臉部偵測結果摘要。"""
    face_count: int
    has_faces: bool
    largest_face_ratio: float  # 最大臉部面積 / 畫面面積


class ImageMetadata(BaseModel):
    """圖片素材的感知元數據。"""
    width: int
    height: int
    aspect_ratio: float
    creation_time: str = ""
    location_gps: str = ""
    # ── 語意分析（LLM）──
    caption: Optional[str] = None
    cinematic_critique: Optional[str] = None
    mood: str = ""
    scene_tags: list[str] = []
    camera_angle: str = ""
    action_tags: list[str] = []
    time_of_day: str = ""
    # ── 品質評分 ──
    technical_score: float
    aesthetic_score: float
    # ── 視覺特徵（cv2/PIL）──
    brightness: float = 0.0
    color_temperature: str = ""
    dominant_colors: list[str] = []
    # ── 主體定位 ──
    subject_bbox: SubjectBbox
    crop_feasibility: str = "full"
    faces: Optional[FaceInfo] = None


class VideoMetadata(BaseModel):
    """一般影片素材的感知元數據（VideoProcessor 輸出）。"""
    width: int
    height: int
    aspect_ratio: float = 0.0
    duration: float
    fps: float
    creation_time: str = ""
    location_gps: str = ""
    # ── 音訊分析 ──
    has_speech: bool = False
    spoken_language: str = ""
    audio_transcript: dict[str, Any] = {}
    environmental_sounds: list[Any] = []
    # ── 語意分析（LLM）──
    caption: Optional[str] = None
    cinematic_critique: str = ""
    mood: str = ""
    scene_tags: list[str] = []
    camera_angle: str = ""
    action_tags: list[str] = []
    time_of_day: str = ""
    # ── 品質評分 ──
    technical_score: float
    aesthetic_score: float
    # ── 視覺特徵（cv2/PIL）──
    brightness: float = 0.0
    color_temperature: str = ""
    dominant_colors: list[str] = []
    motion_intensity: str = ""
    # ── 主體定位 ──
    subject_bbox: SubjectBbox
    crop_feasibility: str = "full"
    faces: Optional[FaceInfo] = None
    # ── 影片結構 ──
    scene_cuts: list[float] = []


class ComplexVideoMetadata(BaseModel):
    """
    複雜影片素材的感知元數據（ComplexVideoProcessor 輸出）。
    以 multimodal_event_index 取代單一 subject_bbox，提供逐段視聽高潮點；
    複雜影片依靠事件區塊判斷，不進行整體畫質/美學打分。
    """
    width: int
    height: int
    aspect_ratio: float = 0.0
    duration: float
    fps: float
    creation_time: str = ""
    location_gps: str = ""
    # ── 音訊分析 ──
    has_speech: bool = False
    spoken_language: str = ""
    audio_transcript: dict[str, Any] = {}
    environmental_sounds: list[Any] = []
    # ── 語意分析（LLM，全局）──
    cinematic_critique: str = ""
    mood: str = ""
    scene_tags: list[str] = []
    camera_angle: str = ""
    action_tags: list[str] = []
    time_of_day: str = ""
    # ── 視覺特徵（cv2/PIL）──
    brightness: float = 0.0
    color_temperature: str = ""
    dominant_colors: list[str] = []
    # ── 影片結構 ──
    is_dense_indexed: bool = True
    scene_cuts: list[float] = []
    multimodal_event_index: list[dict[str, Any]] = []


class ProcessorResult(BaseModel):
    """
    媒體處理器的統一回傳包裝（Strategy 模式的統一輸出介面）。

    status 可能的值：
      - "success"  → metadata 有值
      - "rejected" → reason 有值（畫質不足）
      - "error"    → message 有值（例外發生）
    """
    status: str
    type: Optional[str] = None   # "image" | "video"
    file: str
    metadata: Optional[ImageMetadata | VideoMetadata | ComplexVideoMetadata] = None
    reason: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        """
        輸出為下游相容的 dict。
        只移除最外層值為 None 的欄位，保留 metadata 內層的所有欄位。
        """
        data = self.model_dump()
        return {key: value for key, value in data.items() if value is not None}
