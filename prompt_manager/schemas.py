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

from config.color_presets import COLOR_PRESET_NAMES, primitive_range


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


# 調色預設名 enum：刻意**動態**由 SSOT (color_presets.json) 的 preset 名建立，
# 而非手寫成員——如此「新增一個 look = 在 JSON 加一筆」即可，schema / prompt / 前端全自動跟上，
# 從根拔除過去『濾鏡名手抄四處』的飄移 (對應 docs/editing_capability_roadmap.md 方向三)。
# 以函式式 Enum API + type=str 等價於 `class ColorPreset(str, Enum)`，供 Gemini response_schema
# 與 schema_to_text 兩條路徑一致取用。preset 名須為合法 Python 識別字 (用底線、勿用連字號)。
ColorPreset = Enum(
    "ColorPreset",
    {name.upper(): name for name in COLOR_PRESET_NAMES},
    type=str,
)
ColorPreset.__doc__ = "片段調色預設名（動態源自 color_presets.json 的 presets）。"

# 「無調色」預設名 (具名常數，供 ClipColor 預設值以值反查對應 enum 成員，不依賴大寫後的屬性名)
_COLOR_PRESET_NONE = "none"


class TransitionType(str, Enum):
    """進場轉場：前端僅實作 fade（其餘等同無轉場），故只開放 none / fade。"""
    NONE = "none"
    FADE = "fade"


class PipPosition(str, Enum):
    """畫中畫位置：前端僅對 top_right / bottom_left 套定位樣式，故只開放此二者。"""
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"


class TextSize(str, Enum):
    """字幕字級分級：不直接給 px，由前端 SUBTITLE_SIZE_MAP 統一換算成具體尺寸（單一來源）。"""
    S = "s"
    M = "m"
    L = "l"
    XL = "xl"


class TextColor(str, Enum):
    """字幕顏色：精選『在任何畫面都讀得到』的色票，避免 LLM 自由配出不可讀組合。"""
    WHITE = "white"
    BLACK = "black"
    YELLOW = "yellow"
    ACCENT = "accent"


class TextOutline(str, Enum):
    """字幕描邊 / 陰影樣式：拉開文字與背景的對比，是字幕『不糊進畫面』的關鍵。"""
    NONE = "none"
    OUTLINE = "outline"
    SHADOW = "shadow"
    OUTLINE_SHADOW = "outline_shadow"


class TextBackground(str, Enum):
    """字幕底框樣式：在雜亂背景上墊一層底以保可讀性。"""
    NONE = "none"
    SOLID = "solid"
    BLUR = "blur"
    PILL = "pill"


class TextAnimation(str, Enum):
    """字幕進出場動畫：render-time 由前端以 interpolate 實作（與轉場 fade 同源）。"""
    NONE = "none"
    FADE = "fade"
    SLIDE_UP = "slide_up"
    POP = "pop"


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
    clip_id: str = Field(default="", description="子畫面素材 ID：一字不差照抄素材庫對應素材的 id（含 raw/ 或 standardized/ 前綴與 _std 後綴）；嚴禁改寫、去前綴或自行拼路徑")
    source_start: float = Field(default=0.0, description="子畫面素材擷取起點（秒）")
    position: PipPosition = Field(default=PipPosition.TOP_RIGHT, description="子畫面位置")


# ── 片段調色 (color grading)：primitive 數值範圍同源於 SSOT (color_presets.json)，供 Field 約束 ──
# 集中具名，禁 magic number；範圍與 Inspector 滑桿邊界同源，故不會飄移。
_BRIGHTNESS_MIN, _BRIGHTNESS_MAX = primitive_range("brightness")
_CONTRAST_MIN, _CONTRAST_MAX = primitive_range("contrast")
_SATURATE_MIN, _SATURATE_MAX = primitive_range("saturate")
_SEPIA_MIN, _SEPIA_MAX = primitive_range("sepia")
_BLUR_MIN, _BLUR_MAX = primitive_range("blur")
_GRAYSCALE_MIN, _GRAYSCALE_MAX = primitive_range("grayscale")


class ClipColor(BaseModel):
    """
    片段調色設定：引用一個命名 preset，並可微調（覆寫）個別 primitive（照 :class:`PipVideo` 巢狀物件模式）。

    解析規則（前端 render-time）：先取 ``preset`` 的一包 primitive 數值為基底，再以本物件中『有填值』的
    primitive 逐一覆寫，最後機械式組成 CSS filter。primitive 留空（null）= 沿用 preset 對應值。
    數值範圍由 Field 依 SSOT 約束，杜絕導演輸出越界值。
    範例：``{preset: "cinematic", brightness: 0.8}`` = 電影感但再暗一點。
    """
    preset: ColorPreset = Field(
        default=ColorPreset(_COLOR_PRESET_NONE),
        description="調色預設名：先選一個當整支基調（none 為不調色）",
    )
    brightness: Optional[float] = Field(
        default=None, ge=_BRIGHTNESS_MIN, le=_BRIGHTNESS_MAX,
        description="亮度覆寫（留空=沿用 preset；1.0 原樣、<1 變暗）",
    )
    contrast: Optional[float] = Field(
        default=None, ge=_CONTRAST_MIN, le=_CONTRAST_MAX,
        description="對比覆寫（留空=沿用 preset；1.0 原樣、>1 更強烈）",
    )
    saturate: Optional[float] = Field(
        default=None, ge=_SATURATE_MIN, le=_SATURATE_MAX,
        description="飽和覆寫（留空=沿用 preset；0=灰、1 原樣、>1 更濃）",
    )
    sepia: Optional[float] = Field(
        default=None, ge=_SEPIA_MIN, le=_SEPIA_MAX,
        description="棕褐覆寫（留空=沿用 preset；0 無、1 全棕褐、偏暖復古）",
    )
    blur: Optional[float] = Field(
        default=None, ge=_BLUR_MIN, le=_BLUR_MAX,
        description="模糊覆寫（留空=沿用 preset；單位 px、0 不模糊）",
    )
    grayscale: Optional[float] = Field(
        default=None, ge=_GRAYSCALE_MIN, le=_GRAYSCALE_MAX,
        description="黑白覆寫（留空=沿用 preset；0 彩色、1 全黑白）",
    )


# 字幕垂直位置的合法範圍（0=畫面頂、100=畫面底）；實際會被前端再夾進 safe-area，避免壓到平台 UI。
_TEXT_VPOS_MIN = 0.0
_TEXT_VPOS_MAX = 100.0
_TEXT_VPOS_DEFAULT = 85.0  # ≈ 下三分之一：在底部 UI 之上、又不致頂到主體

# 字幕水平位置的合法範圍（0=畫面左、100=畫面右）；同樣會被前端夾進 safe-area（右側留大避平台互動鈕列）。
_TEXT_HPOS_MIN = 0.0
_TEXT_HPOS_MAX = 100.0
_TEXT_HPOS_DEFAULT = 50.0  # 置中：閱讀型字幕的安全預設


class TextOverlay(BaseModel):
    """
    畫面文字疊加（字幕 / 花字）的結構化樣式 + 計時設定。

    字幕為**獨立於片段**的時間軸物件（見 :class:`DirectorBlueprint` 的 ``text_overlays``）：帶絕對
    ``start_at/end_at``，故可跨多個片段持續顯示、同一時段亦可並存多條。樣式以 enum / bounded float
    結構化，讓渲染端、導演 LLM、Inspector 三方共讀同一份欄位（照 :class:`PipVideo` 巢狀物件模式）。
    位置採『連續垂直 / 水平 %』：讓導演依主體 bbox 把字幕放在不擋主體處；上下左右邊界由前端夾進
    safe-area，故 LLM 不需自行算平台 UI 遮擋。
    """
    text: str = Field(default="", description="要顯示在畫面上的字幕文字")
    start_at: float = Field(default=0.0, description="字幕在總時間軸上的開始秒數（可跨多個片段）")
    end_at: float = Field(default=0.0, description="字幕在總時間軸上的結束秒數")
    vertical_position: float = Field(
        default=_TEXT_VPOS_DEFAULT, ge=_TEXT_VPOS_MIN, le=_TEXT_VPOS_MAX,
        description="字幕垂直錨點：0=畫面頂、100=畫面底。依主體 bbox 放在不擋主體處，系統會再夾進 safe-area",
    )
    horizontal_position: float = Field(
        default=_TEXT_HPOS_DEFAULT, ge=_TEXT_HPOS_MIN, le=_TEXT_HPOS_MAX,
        description="字幕水平錨點：0=畫面左、100=畫面右、50=置中。依主體 bbox 避主體；閱讀型字幕用 50，系統會再夾進 safe-area",
    )
    size: TextSize = Field(default=TextSize.M, description="字級分級")
    color: TextColor = Field(default=TextColor.WHITE, description="字幕顏色（精選可讀色票）")
    outline: TextOutline = Field(default=TextOutline.OUTLINE_SHADOW, description="描邊 / 陰影樣式（拉開與背景的對比）")
    background: TextBackground = Field(default=TextBackground.NONE, description="底框樣式")
    animation: TextAnimation = Field(default=TextAnimation.FADE, description="進出場動畫")


class Clip(BaseModel):
    """
    時間軸上的單一片段。

    ``reason`` 刻意置於**第一個欄位**：藉結構化輸出的隱含 property ordering 逼模型「先寫
    導演決策理由、再填參數」，把原本沒人消費的欄位轉成提升決策品質的 inline 推理鏈。
    """
    reason: str = Field(default="", description="導演決策說明：先想清楚轉場 / 變速 / 混音 / 選材的考量，再填下方參數")
    clip_id: str = Field(default="", description="素材 ID：必須一字不差照抄素材庫對應素材的 id 欄位（含 raw/ 或 standardized/ 前綴與 _std 後綴）；嚴禁改寫、簡化、去前綴或自行拼路徑")
    start_at: float = Field(default=0.0, description="總時間軸上的開始秒數")
    end_at: float = Field(default=0.0, description="總時間軸上的結束秒數")
    source_start: float = Field(default=0.0, description="素材擷取起點（秒）")
    source_end: float = Field(default=0.0, description="素材擷取終點（秒）；圖片可為 0")
    playback_rate: float = Field(default=1.0, description="播放速度（0.5 慢動作、2.0 快轉）；須滿足 (source_end-source_start)/playback_rate = end_at-start_at")
    object_position: str = Field(default="50% 50%", description="裁切定位點，如 '44% 77%'，依主體 bbox 中心計算")
    scale: float = Field(default=1.0, description="縮放比例（1.0 不縮放、1.2 放大20%）")
    color: ClipColor = Field(
        default_factory=ClipColor,
        description="調色：引用 preset 當基調 + 可選 primitive 微調（取代舊 filter 欄位）",
    )
    transition_in: TransitionType = Field(default=TransitionType.NONE, description="進場轉場")
    # 注意：運鏡（motion）刻意不在 LLM 輸出 schema 內。實際運鏡一律由前端引擎依素材 / 配樂節拍自動套用，
    # LLM 無從決策（過去要求它「一律填 auto」等於佔位空轉），故由 DirectorFacade 後端統一補預設 'auto'；
    # 使用者要逐段覆寫時於前端 ClipInspector 就地編輯，不經 LLM。
    clip_volume: float = Field(default=1.0, description="原音音量（0.0 靜音、1.0 最大）")
    bgm_volume: float = Field(default=1.0, description="播到此片段時全局 BGM 的動態音量權重（Audio Ducking）")
    # 註：字幕已從片段解耦，改為 DirectorBlueprint.text_overlays 獨立字幕軌（可跨片段、可同框多條），
    # 故此處不再有 text_overlay 欄位。
    pip_video: Optional[PipVideo] = Field(default=None, description="畫中畫設定；無則為 null")


class DirectorBlueprint(BaseModel):
    """導演剪輯藍圖：全局配樂 + 片段時間軸 + 獨立字幕軌（驅動 Remotion 渲染）。"""
    bgm_track: BgmTrack = Field(default_factory=BgmTrack, description="全局背景音樂設定")
    timeline: list[Clip] = Field(default_factory=list, description="依序排列的片段時間軸")
    text_overlays: list[TextOverlay] = Field(
        default_factory=list,
        description="畫面字幕清單（獨立於片段，可跨片段持續顯示、同一時段可並存多條）",
    )


# ──────────────────────────────────────────────────────────────────────────────
# ⑤-0 導演選角（兩階段 Plan-then-Fill 的第一段：選材，只輸出要用的素材 id）
# ──────────────────────────────────────────────────────────────────────────────
class CastingCard(BaseModel):
    """
    第一段 Casting 看的「精簡素材卡片」（由 ``ContextCompressor`` 從完整 dossier 投影而來）。

    刻意只帶支撐『選材 / 排序 / 粗略時長』的欄位：逐句時間戳 chunks、完整事件索引、bbox、
    主體候選、攝影評論等「精修才需要」的重料一律不入卡片（留待第二段按 id 取完整 dossier），
    這正是兩階段縮小 context 的關鍵。影片專屬欄位以 ``Optional`` 表示，圖片卡片經
    ``model_dump(exclude_none=True)`` 後自動精簡。本模型是『注入 prompt 的資料結構』，
    非 Gemini ``response_schema``。
    """
    id: str = Field(default="", description="素材 ID（即 clip_id；選回時須原樣照抄）")
    type: str = Field(default="", description="image / video")
    aes: float = Field(default=0.0, description="美學分（選材優先取高分）")
    tech: Optional[float] = Field(default=None, description="技術畫質分")
    cap: str = Field(default="", description="客觀內容描述（全文）")
    mood: str = Field(default="", description="情緒")
    scene_tags: list[str] = Field(default_factory=list, description="場景標籤")
    actions: list[str] = Field(default_factory=list, description="動作標籤")
    crop: str = Field(default="full", description="9:16 可裁性")
    time: str = Field(default="", description="拍攝時間")
    geo: str = Field(default="", description="拍攝地點 GPS")
    # 影片專屬（圖片為 None，dump 時排除）
    dur: Optional[float] = Field(default=None, description="影片時長（秒）")
    motion: Optional[str] = Field(default=None, description="動態強度")
    has_speech: Optional[bool] = Field(default=None, description="是否有人聲")
    transcript_text: Optional[str] = Field(default=None, description="完整逐字稿（無時間戳；帶時間戳 chunks 留第二段）")
    event_digest: Optional[list[str]] = Field(default=None, description="複雜影片各事件的畫面動作摘要（visual_layer，無時間戳）")


class CastingSelection(BaseModel):
    """
    導演選角結果（第一段 Casting 的結構化輸出）：從素材庫粗篩出一個『候選池』交給第二段。

    ``rationale`` 刻意置首（同 :class:`Clip` 的手法）：藉結構化輸出的隱含 property ordering 逼模型
    『先想清楚故事走向與所需素材，再列出 id』，把 think-first 轉成選材品質。
    刻意只輸出 id、且是『候選池（粗篩）』而非最終定剪：最終要用哪些、精準排序 / 時長 / 裁切 / 混音
    全部交給第二段在這個池子上自由發揮，不讓較弱的選角模型框死較強的精修模型。
    """
    rationale: str = Field(default="", description="整體選材思路：先想清楚故事走向、需要哪些素材，再列出 id")
    selected_ids: list[str] = Field(default_factory=list, description="候選池素材 id 清單（一字不差照抄素材庫 id，含 raw/ 或 standardized/ 前綴與 _std 後綴）；依『相關 / 重要程度』由高到低排序（供必要時取捨用，非播放順序，播放順序由第二段決定）")


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
