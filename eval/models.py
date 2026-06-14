"""所有資料結構（依 CLAUDE.md：一律用 pydantic 定義）。

涵蓋 spec（DatasetSpec/GroupSpec）、抓取候選（ClipCandidate）、策展後寫入 dataset 的逐段
metadata（ClipMetadata）、prompt 變異（PromptVariant），以及打包用的 manifest。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .constants import (
    DEFAULT_CANDIDATE_MULTIPLIER,
    DEFAULT_TARGET_TOTAL_SECONDS,
)


class SourcePlatform(str, Enum):
    """素材來源平台（值即設定檔/路徑中使用的字串）。"""

    PEXELS = "pexels"
    PIXABAY = "pixabay"


class GroupSpec(BaseModel):
    """單一「素材組」的規格。"""

    group_id: str = Field(description="組別唯一識別碼，會用於目錄與檔名")
    theme: str = Field(description="主題（中文），用於 prompt 生成")
    keywords: list[str] = Field(min_length=1, description="API 搜尋關鍵字（建議英文）")
    prompt_count: int = Field(ge=1, description="要生成幾個 user prompt")
    # 秒數預算：該組需要的影片總秒數；None 時繼承 DatasetSpec.default_target_total_seconds
    target_total_seconds: float | None = Field(default=None, gt=0)
    # 片段數為可選的額外上限/提示；主要驅動改用秒數預算
    target_clip_count: int | None = Field(default=None, gt=0)


class DatasetSpec(BaseModel):
    """整份 dataset 的規格（階段 0 由 YAML 載入並驗證）。"""

    dataset_version: str = Field(description="版本字串，作為凍結輸出的目錄名")
    output_dir: str = Field(description="所有產物的根目錄")
    sources: list[SourcePlatform] = Field(min_length=1, description="啟用的來源平台")
    groups: list[GroupSpec] = Field(min_length=1)
    default_target_total_seconds: float = Field(
        default=DEFAULT_TARGET_TOTAL_SECONDS, gt=0,
        description="各組未指定 target_total_seconds 時的預設秒數預算",
    )
    candidate_multiplier: float = Field(
        default=DEFAULT_CANDIDATE_MULTIPLIER, ge=1.0,
        description="候選池目標 = 秒數預算 × 此倍數",
    )

    def resolved_target_seconds(self, group: GroupSpec) -> float:
        """回傳該組實際採用的秒數預算（自身優先，否則用 dataset 預設）。"""
        return group.target_total_seconds or self.default_target_total_seconds


class ClipCandidate(BaseModel):
    """抓取階段的候選片段（含原始 metadata 與本機落地路徑）。"""

    source_platform: SourcePlatform
    video_id: str
    page_url: str = Field(description="來源平台上的原始頁面 URL")
    author_name: str
    author_url: str | None = None
    license: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_sec: float = Field(gt=0)
    download_url: str
    thumbnail_url: str | None = None
    keyword: str | None = Field(default=None, description="命中的搜尋關鍵字（供追溯）")
    local_path: str | None = Field(default=None, description="影片本機路徑（下載後填入）")
    thumbnail_path: str | None = Field(default=None, description="縮圖本機路徑")
    quality_score: float | None = Field(default=None, description="品質啟發式評分 0~1")

    @property
    def aspect_ratio(self) -> float:
        """長寬比 width / height。"""
        return self.width / self.height

    @property
    def is_vertical(self) -> bool:
        """是否為直式（height > width）。"""
        return self.height > self.width

    @property
    def cache_key(self) -> str:
        """跨平台唯一鍵（避免不同平台 video_id 撞號），亦作為選取/去重的 token。"""
        return f"{self.source_platform.value}:{self.video_id}"


class ClipMetadata(BaseModel):
    """策展後寫入 dataset 的逐段 metadata（檔名亂序、但可追溯回原始 video_id）。"""

    clip_name: str = Field(description="亂序命名後的檔名主體，如 clip_01")
    source_platform: SourcePlatform
    original_video_id: str
    page_url: str
    author_name: str
    author_url: str | None = None
    license: str
    width: int
    height: int
    duration_sec: float


class PromptVariant(BaseModel):
    """單一 user prompt 變異（含多樣性標記，便於分析涵蓋度）。"""

    text: str
    detail_level: str = Field(description="詳細度：minimal/light/specific/detailed")
    tone: str = Field(description="語氣標記")
    scenario: str = Field(description="情境標記")


class CurationSummary(BaseModel):
    """單組策展摘要（策展階段寫出、打包階段讀取）。"""

    curation_mode: str = Field(description="manual 或 auto_fallback")
    total_seconds: float
    clip_count: int


class GroupManifest(BaseModel):
    """打包時單組的摘要。"""

    group_id: str
    theme: str
    clip_count: int
    total_seconds: float
    prompt_count: int
    curation_mode: str = Field(description="manual 或 auto_fallback")


class DatasetManifest(BaseModel):
    """打包時整份 dataset 的 manifest。"""

    dataset_version: str
    created_at: str
    sources: list[SourcePlatform]
    group_count: int
    groups: list[GroupManifest]
