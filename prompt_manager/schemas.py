"""
Prompt 輸出結構的單一事實來源 (Single Source of Truth)。

本模組集中定義「LLM 任務輸出」的兩件事：
1. **語意詞彙表 (Enum)**：mood / scene_tags / camera_angle 等的合法值，過去散落在各 prompt
   字串、已飄移；集中於此後，Gemini 走 ``response_schema`` 直接用 enum 強制約束，
   Qwen 走 :func:`schema_to_text` 把同一份定義序列化成文字塞進 prompt，兩條路徑永不飄移。
2. **輸出 schema (pydantic v2 model)**：每支 prompt 對應一個 model，作為 Gemini
   ``response_schema`` 的型別。這些 model 是各 ``assembly_*_stage`` 從 ``vlm.get(...)`` 取用
   欄位的「LLM 該產出部分」，刻意**不含** assembly 自行計算的 width / 畫質分 / 解析後 bbox /
   crop / faces —— 那些不是模型輸出，故不入 LLM schema。

⚠️ bbox 軸序：圖片 / Qwen 走 ``[x1,y1,x2,y2]``、Gemini 影片走 ``[ymin,xmin,ymax,xmax]``，
皆 0–1000 正規化整數。這是刻意迎合各家模型原生慣例以提高框準度；下游 ``vlm_bbox_utils``
已能依來源換算統一成 ``SubjectBbox(0–100)``，故軸序差異不外溢到導演端。各 prompt 的心法
文字會明確指定該支該用哪種軸序。
"""
from __future__ import annotations

import types
from enum import Enum
from typing import Optional, Union, get_args, get_origin

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# 語意詞彙表 (Enum)：取代散落各 prompt 的 magic string，作為唯一合法值來源
# ──────────────────────────────────────────────────────────────────────────────
class Mood(str, Enum):
    """整體 / 區段情緒氛圍。"""
    ENERGETIC = "energetic"
    CALM = "calm"
    ROMANTIC = "romantic"
    DRAMATIC = "dramatic"
    HUMOROUS = "humorous"
    MELANCHOLIC = "melancholic"
    INSPIRATIONAL = "inspirational"
    TENSE = "tense"


class SceneTag(str, Enum):
    """場景標籤（可多選）。"""
    OUTDOOR = "outdoor"
    INDOOR = "indoor"
    NATURE = "nature"
    URBAN = "urban"
    PORTRAIT = "portrait"
    CROWD = "crowd"
    FOOD = "food"
    ANIMAL = "animal"
    VEHICLE = "vehicle"
    SPORT = "sport"
    NIGHT = "night"


class CameraAngle(str, Enum):
    """鏡頭視角。"""
    CLOSE_UP = "close-up"
    MEDIUM = "medium"
    WIDE = "wide"
    AERIAL = "aerial"
    POV = "POV"
    UNKNOWN = "unknown"


class ActionTag(str, Enum):
    """動作標籤（可多選）。"""
    DANCING = "dancing"
    TALKING = "talking"
    RUNNING = "running"
    COOKING = "cooking"
    DRIVING = "driving"
    PLAYING = "playing"
    WORKING = "working"
    WALKING = "walking"
    PERFORMING = "performing"
    SITTING = "sitting"


class TimeOfDay(str, Enum):
    """時段。"""
    GOLDEN_HOUR = "golden_hour"
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"
    INDOOR = "indoor"
    UNKNOWN = "unknown"


class MusicGenre(str, Enum):
    """配樂曲風（範本配樂偵測用）。"""
    POP = "pop"
    ROCK = "rock"
    HIPHOP = "hiphop"
    ELECTRONIC = "electronic"
    JAZZ = "jazz"
    CLASSICAL = "classical"
    AMBIENT = "ambient"
    FOLK = "folk"
    CINEMATIC = "cinematic"
    OTHER = "other"


class ClipFilter(str, Enum):
    """片段 CSS 濾鏡：僅列前端 ClipComponent 真正實作的值（對齊現況，不含假效果）。"""
    NONE = "none"
    CINEMATIC = "cinematic"
    GRAYSCALE = "grayscale"
    BLUR = "blur"


class TransitionType(str, Enum):
    """進場轉場：前端僅實作 fade（其餘等同無轉場），故只開放 none / fade。"""
    NONE = "none"
    FADE = "fade"


class PipPosition(str, Enum):
    """畫中畫位置：前端僅對 top_right / bottom_left 套定位樣式，故只開放此二者。"""
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"


# ──────────────────────────────────────────────────────────────────────────────
# 共用子結構
# ──────────────────────────────────────────────────────────────────────────────
class SubjectCandidateOut(BaseModel):
    """
    VLM 輸出的單一候選主體（未解析的原始形狀）。

    ``bbox`` 為長度 4 的整數陣列、0–1000 正規化；**軸序由各 prompt 的心法指定**
    （圖片 / Qwen 用 ``[x1,y1,x2,y2]``、Gemini 影片用 ``[ymin,xmin,ymax,xmax]``）。
    下游 ``vlm_bbox_utils`` 依來源換算成統一的 ``SubjectBbox``。
    """
    bbox: list[int] = Field(default_factory=list, description="主體框，長度4整數陣列，0–1000正規化（只框單一主體）")
    label: str = Field(default="", description="主體的簡短中文描述，如『紅衣女子』『衝浪板』")
    confidence: float = Field(default=0.0, description="此為畫面最主要主體的把握程度，0~1小數")


class TranscriptChunk(BaseModel):
    """逐句轉錄片段。"""
    text: str = Field(default="", description="這一句話的文字")
    timestamp: list[float] = Field(default_factory=list, description="[起, 訖] 秒，兩個小數")


class AudioTranscript(BaseModel):
    """完整音訊轉錄結果（人聲逐字稿 + 帶時間戳的分句）。"""
    text: str = Field(default="", description="完整逐字稿；無人聲填空字串")
    language: str = Field(default="", description="語言代碼，如 en / zh；無人聲填空字串")
    chunks: list[TranscriptChunk] = Field(default_factory=list, description="帶時間戳的分句清單")


class EnvironmentalSound(BaseModel):
    """環境音偵測項。"""
    label: str = Field(default="", description="環境音標籤，如 music / speech / applause / wind")
    score: float = Field(default=0.0, description="信心分數 0~1")


# ──────────────────────────────────────────────────────────────────────────────
# ① / ② 基本媒體分析 & 深度圖片分析（共用同一 schema；deep 為更強模型 + 更細描述）
# ──────────────────────────────────────────────────────────────────────────────
class BasicMediaSemantics(BaseModel):
    """
    圖片 / 簡單影片的全局語意分析輸出（BASIC_MEDIA_ANALYSIS、DEEP_IMAGE_ANALYSIS 共用）。

    對齊 ``assembly_image_stage`` / ``assembly_video_stage._build_simple`` 取用的語意欄位。
    bbox 軸序為 ``[x1,y1,x2,y2]``（圖片 / Qwen / deep 皆走 ``parse_qwen_candidates``）。
    """
    caption: str = Field(default="", description="對素材主要內容與動作的客觀描述")
    cinematic_critique: str = Field(default="", description="鏡頭語言與情緒氛圍的攝影評論（光影、色調、構圖）")
    mood: Mood = Field(default=Mood.CALM, description="整體情緒")
    scene_tags: list[SceneTag] = Field(default_factory=list, description="場景標籤，可多選")
    camera_angle: CameraAngle = Field(default=CameraAngle.UNKNOWN, description="主要鏡頭視角")
    action_tags: list[ActionTag] = Field(default_factory=list, description="動作標籤，可多選")
    time_of_day: TimeOfDay = Field(default=TimeOfDay.UNKNOWN, description="時段")
    subject_candidates: list[SubjectCandidateOut] = Field(
        default_factory=list,
        description="畫面最重要的前幾名主體，依重要程度由高到低；純風景 / 抽象畫面填空陣列",
    )


# ──────────────────────────────────────────────────────────────────────────────
# 多模態事件基底（③ video_event 與 ④ template 共用，各自加料）
# ──────────────────────────────────────────────────────────────────────────────
class MultimodalEventBase(BaseModel):
    """一段連續的多模態事件區塊：視覺層 + 聽覺層 + 起訖秒數（video / template 共用基底）。"""
    start_time: float = Field(default=0.0, description="區段起點（秒，小數）")
    end_time: float = Field(default=0.0, description="區段終點（秒，小數）")
    visual_layer: str = Field(default="", description="此區段的畫面動作描述")
    audio_layer: str = Field(default="", description="此區段配樂 / 人聲 / 環境音的起伏描述")
    mood: Mood = Field(default=Mood.CALM, description="此區段情緒")
    action_tags: list[ActionTag] = Field(default_factory=list, description="此區段動作標籤")


class VideoEvent(MultimodalEventBase):
    """複雜影片的事件區塊：在基底上加『關鍵時間點』與『該時間點的主體框』。"""
    key_timestamp: float = Field(
        default=0.0,
        description="此區段最關鍵的時間點（秒）：聲音爆發或動作高潮的精確秒數",
    )
    subject_candidates: list[SubjectCandidateOut] = Field(
        default_factory=list,
        description="key_timestamp 當下畫面最重要的前幾名主體；bbox 軸序為 [ymin,xmin,ymax,xmax]",
    )


class TemplateEvent(MultimodalEventBase):
    """範本影片的事件區塊：只需風格 / 節奏參考，故為基底本身（不需主體框與關鍵點）。"""


# ──────────────────────────────────────────────────────────────────────────────
# ③ 影片事件索引（複雜影片：事件 + 全局語意 + 音訊轉錄）
# ──────────────────────────────────────────────────────────────────────────────
class VideoEventIndexSemantics(BaseModel):
    """
    複雜影片的逐時間段多模態事件索引 + 全局語意 + 音訊結構化輸出（VIDEO_EVENT_INDEX）。

    對齊 ``assembly_video_stage._build_complex`` 與 ``_apply_gemini_audio`` 取用的欄位。
    """
    cinematic_critique: str = Field(default="", description="整支影片的運鏡與情緒氛圍評論")
    mood: Mood = Field(default=Mood.CALM, description="整體情緒")
    scene_tags: list[SceneTag] = Field(default_factory=list, description="場景標籤，可多選")
    camera_angle: CameraAngle = Field(default=CameraAngle.UNKNOWN, description="主要鏡頭視角")
    action_tags: list[ActionTag] = Field(default_factory=list, description="全局動作標籤，可多選")
    time_of_day: TimeOfDay = Field(default=TimeOfDay.UNKNOWN, description="時段")
    has_speech: bool = Field(default=False, description="全片是否有人聲")
    spoken_language: str = Field(default="", description="人聲語言代碼，如 en / zh；無人聲填空字串")
    audio_transcript: AudioTranscript = Field(default_factory=AudioTranscript, description="逐句轉錄與時間戳")
    environmental_sounds: list[EnvironmentalSound] = Field(default_factory=list, description="主要環境音")
    multimodal_event_index: list[VideoEvent] = Field(
        default_factory=list, description="依時間軸拆解的連續多模態事件區塊"
    )


# ──────────────────────────────────────────────────────────────────────────────
# ④ 範本分析（事件 + 全局語意 + 音訊轉錄 + 配樂偵測）
# ──────────────────────────────────────────────────────────────────────────────
class SongGuess(BaseModel):
    """範本配樂的歌名最佳猜測（可能有誤，務必附 confidence、寧缺勿造）。"""
    title: str = Field(default="", description="猜測歌名；不確定留空")
    artist: str = Field(default="", description="猜測歌手；不確定留空")
    confidence: float = Field(default=0.0, description="猜測把握程度 0~1；不確定給低分")


class MusicAnalysis(BaseModel):
    """範本配樂偵測：曲風 / 情緒 / 是否有歌聲 / 歌名猜測。"""
    music_style: str = Field(default="", description="自由描述曲風 / 編制，如 'lo-fi chill hip-hop, mellow piano'")
    genre: MusicGenre = Field(default=MusicGenre.OTHER, description="曲風分類")
    mood: Mood = Field(default=Mood.CALM, description="音樂情緒")
    has_vocals: bool = Field(default=False, description="是否有歌聲")
    song_guess: SongGuess = Field(default_factory=SongGuess, description="歌名最佳猜測")


class TemplateAnalysisSemantics(BaseModel):
    """
    範本影片的風格 / 節奏 / 配樂分析輸出（TEMPLATE_ANALYSIS）。

    對齊 ``assembly_video_stage._build_template`` 取用的欄位：刻意**無** camera_angle /
    time_of_day（範本 DNA 不消費），多了 ``music_analysis``（範本專屬配樂偵測）。
    """
    cinematic_critique: str = Field(default="", description="整支範本的運鏡與情緒氛圍評論")
    mood: Mood = Field(default=Mood.CALM, description="整體情緒")
    scene_tags: list[SceneTag] = Field(default_factory=list, description="場景標籤，可多選")
    action_tags: list[ActionTag] = Field(default_factory=list, description="全局動作標籤，可多選")
    audio_transcript: AudioTranscript = Field(default_factory=AudioTranscript, description="逐句轉錄與時間戳")
    music_analysis: MusicAnalysis = Field(default_factory=MusicAnalysis, description="範本配樂偵測")
    multimodal_event_index: list[TemplateEvent] = Field(
        default_factory=list, description="依時間軸拆解的連續多模態事件區塊"
    )


# ──────────────────────────────────────────────────────────────────────────────
# ⑥ 音樂搜尋關鍵字
# ──────────────────────────────────────────────────────────────────────────────
class MusicSearchQuery(BaseModel):
    """把使用者需求轉成的配樂搜尋關鍵字。"""
    search_query: str = Field(default="", description="配樂搜尋詞：指名歌手歌名 或 英文音樂關鍵字")


# ──────────────────────────────────────────────────────────────────────────────
# ⑤ 導演剪輯藍圖（Remotion 可渲染 JSON）
# ──────────────────────────────────────────────────────────────────────────────
class BgmTrack(BaseModel):
    """
    全局背景音樂設定。

    ⚠️ 刻意**無 track_id**：實際配樂檔由後端依配樂 DNA 注入（``director_service`` 覆寫），
    LLM 不該也無法決定。模型只負責起播位置與基礎音量。
    """
    start_at: float = Field(default=0.0, description="整個影片時間軸上音樂開始播放的秒數（通常 0.0）")
    source_start: float = Field(default=0.0, description="從音樂檔案的第幾秒開始擷取")
    volume: float = Field(default=1.0, description="音樂基礎音量 0.0~1.0")


class PipVideo(BaseModel):
    """畫中畫（子畫面）疊加設定。"""
    clip_id: str = Field(default="", description="子畫面的素材 ID（relpath）")
    source_start: float = Field(default=0.0, description="子畫面素材擷取起點（秒）")
    position: PipPosition = Field(default=PipPosition.TOP_RIGHT, description="子畫面位置")


class Clip(BaseModel):
    """
    時間軸上的單一片段。

    ``reason`` 刻意置於**第一個欄位**：藉結構化輸出的隱含 property ordering 逼模型「先寫
    導演決策理由、再填參數」，把原本沒人消費的欄位轉成提升決策品質的 inline 推理鏈。
    """
    reason: str = Field(default="", description="導演決策說明：先想清楚轉場 / 變速 / 混音 / 選材的考量，再填下方參數")
    clip_id: str = Field(default="", description="素材 ID（relpath，與素材庫 id 一致）")
    start_at: float = Field(default=0.0, description="總時間軸上的開始秒數")
    end_at: float = Field(default=0.0, description="總時間軸上的結束秒數")
    source_start: float = Field(default=0.0, description="素材擷取起點（秒）")
    source_end: float = Field(default=0.0, description="素材擷取終點（秒）；圖片可為 0")
    playback_rate: float = Field(default=1.0, description="播放速度（0.5 慢動作、2.0 快轉）；須滿足 (source_end-source_start)/playback_rate = end_at-start_at")
    object_position: str = Field(default="50% 50%", description="裁切定位點，如 '44% 77%'，依主體 bbox 中心計算")
    scale: float = Field(default=1.0, description="縮放比例（1.0 不縮放、1.2 放大20%）")
    filter: ClipFilter = Field(default=ClipFilter.NONE, description="CSS 濾鏡")
    transition_in: TransitionType = Field(default=TransitionType.NONE, description="進場轉場")
    motion: str = Field(default="auto", description="自動運鏡模式；請一律保持 'auto'，實際運鏡由前端依素材與配樂節拍自動套用（前端可選 auto/none/push_in/pull_out/pan/punch）")
    clip_volume: float = Field(default=1.0, description="原音音量（0.0 靜音、1.0 最大）")
    bgm_volume: float = Field(default=1.0, description="播到此片段時全局 BGM 的動態音量權重（Audio Ducking）")
    overlay_text: str = Field(default="", description="畫面上要疊加的字幕 / 花字；無則留空")
    pip_video: Optional[PipVideo] = Field(default=None, description="畫中畫設定；無則為 null")


class DirectorBlueprint(BaseModel):
    """導演剪輯藍圖：全局配樂 + 片段時間軸（驅動 Remotion 渲染）。"""
    bgm_track: BgmTrack = Field(default_factory=BgmTrack, description="全局背景音樂設定")
    timeline: list[Clip] = Field(default_factory=list, description="依序排列的片段時間軸")


# ──────────────────────────────────────────────────────────────────────────────
# 文字化 helper：把 schema 序列化成文字，供無 structured-output 的模型（Qwen）使用
# ──────────────────────────────────────────────────────────────────────────────
# 基本型別 → 中文型別名（供文字化；禁 magic string 散落）
_PRIMITIVE_LABELS = {str: "字串", float: "小數", int: "整數", bool: "true/false"}


def _describe_type(annotation) -> str:
    """把型別註解轉成給文字模型看的簡短型別說明（含 enum 允許值與巢狀欄位）。"""
    origin = get_origin(annotation)

    # Optional[X] / Union：取非 None 的型別描述
    if origin is Union or origin is types.UnionType:
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return f"{_describe_type(non_none[0])}（可為 null）"
        return " 或 ".join(_describe_type(arg) for arg in non_none)

    # list[X]：描述其元素型別
    if origin is list:
        (inner,) = get_args(annotation)
        return f"陣列，每項為 {_describe_type(inner)}"

    # Enum：列出所有允許值
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        allowed = " / ".join(str(member.value) for member in annotation)
        return f"從這些擇一: {allowed}"

    # 巢狀 pydantic model：展開其欄位
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        sub_fields = ", ".join(
            f"{name}({_describe_type(field.annotation)})"
            for name, field in annotation.model_fields.items()
        )
        return f"物件{{{sub_fields}}}"

    return _PRIMITIVE_LABELS.get(annotation, getattr(annotation, "__name__", str(annotation)))


def schema_to_text(model: type[BaseModel]) -> str:
    """
    把 pydantic schema 序列化成緊湊的欄位說明，供無 ``response_schema`` 的模型（Qwen）使用。

    與 Gemini 的 ``response_schema`` 同源於本模組的 model 定義，確保兩條路徑的欄位與 enum 一致、
    不再各自手抄而飄移。
    """
    lines = ["【嚴格格式】請直接輸出符合下列結構的 JSON，不要包含 markdown 標記或註解："]
    for name, field in model.model_fields.items():
        desc = f"：{field.description}" if field.description else ""
        lines.append(f"- {name} ({_describe_type(field.annotation)}){desc}")
    return "\n".join(lines)
