"""Pipeline 骨架：階段介面、共用情境物件、串接器。

- ``PipelineStage``：所有階段的抽象介面（Strategy）。
- ``BuildContext``：跨階段共用的情境（spec、各種路徑、是否允許 fallback），所有路徑運算集中於此。
- ``DatasetBuildPipeline``：依序執行注入的階段（Pipeline / Chain）。具體階段由 ``cli`` 組裝注入，
  避免 pipeline 反向 import 各階段造成循環依賴。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    CANDIDATES_DIRNAME,
    CANDIDATES_JSON,
    CLIPS_DIRNAME,
    CURATED_DIRNAME,
    CURATION_SUMMARY_JSON,
    FETCH_INDEX_JSON,
    GROUPS_DIRNAME,
    METADATA_JSON,
    PREVIEW_HTML,
    PROMPTS_JSON,
    SELECTION_FILE_SUFFIX,
    SELECTIONS_DIRNAME,
    THUMBNAILS_DIRNAME,
    WORK_DIRNAME,
)
from .logging_setup import get_logger
from .models import DatasetSpec, GroupSpec

logger = get_logger(__name__)


@dataclass
class BuildContext:
    """跨階段共用情境；集中所有路徑運算，階段只透過它取路徑。"""

    spec: DatasetSpec
    output_dir: Path
    # 允許自動 fallback 策展（`all` 子指令或 `--fallback` 時為 True）
    allow_fallback: bool = False

    # ───────────────────────── 工作目錄（中間產物）─────────────────────────
    @property
    def work_dir(self) -> Path:
        """中間產物根目錄。"""
        return self.output_dir / WORK_DIRNAME

    @property
    def selections_dir(self) -> Path:
        """人工選取檔目錄。"""
        return self.work_dir / SELECTIONS_DIRNAME

    def group_work_dir(self, group: GroupSpec) -> Path:
        """單組的工作目錄。"""
        return self.work_dir / group.group_id

    def candidates_dir(self, group: GroupSpec) -> Path:
        """候選影片下載目錄。"""
        return self.group_work_dir(group) / CANDIDATES_DIRNAME

    def thumbnails_dir(self, group: GroupSpec) -> Path:
        """縮圖目錄。"""
        return self.group_work_dir(group) / THUMBNAILS_DIRNAME

    def candidates_json(self, group: GroupSpec) -> Path:
        """候選 metadata 清單檔。"""
        return self.group_work_dir(group) / CANDIDATES_JSON

    def fetch_index_json(self, group: GroupSpec) -> Path:
        """已下載快取索引檔。"""
        return self.group_work_dir(group) / FETCH_INDEX_JSON

    def preview_html(self, group: GroupSpec) -> Path:
        """contact sheet 預覽頁。"""
        return self.group_work_dir(group) / PREVIEW_HTML

    def selection_file(self, group: GroupSpec) -> Path:
        """該組的人工選取檔。"""
        return self.selections_dir / f"{group.group_id}{SELECTION_FILE_SUFFIX}"

    def curated_dir(self, group: GroupSpec) -> Path:
        """策展後（亂序命名）片段目錄。"""
        return self.group_work_dir(group) / CURATED_DIRNAME

    def curated_metadata_json(self, group: GroupSpec) -> Path:
        """策展後逐段 metadata 檔。"""
        return self.curated_dir(group) / METADATA_JSON

    def curation_summary_json(self, group: GroupSpec) -> Path:
        """該組策展摘要（模式/秒數/數量）。"""
        return self.group_work_dir(group) / CURATION_SUMMARY_JSON

    def prompts_json(self, group: GroupSpec) -> Path:
        """該組 user prompts 檔。"""
        return self.group_work_dir(group) / PROMPTS_JSON

    # ───────────────────────── 最終 dataset（凍結輸出）─────────────────────────
    @property
    def dataset_dir(self) -> Path:
        """版本化 dataset 根目錄。"""
        return self.output_dir / self.spec.dataset_version

    def group_dataset_dir(self, group: GroupSpec) -> Path:
        """dataset 內單組目錄。"""
        return self.dataset_dir / GROUPS_DIRNAME / group.group_id

    def group_clips_dir(self, group: GroupSpec) -> Path:
        """dataset 內單組片段目錄。"""
        return self.group_dataset_dir(group) / CLIPS_DIRNAME

    # ───────────────────────── 便利方法 ─────────────────────────
    def resolved_target_seconds(self, group: GroupSpec) -> float:
        """該組實際採用的秒數預算。"""
        return self.spec.resolved_target_seconds(group)


class PipelineStage(ABC):
    """所有 pipeline 階段的抽象介面（Strategy）。"""

    #: 階段名稱（log 與子指令對應）
    name: str = "stage"

    @abstractmethod
    def run(self, context: BuildContext) -> None:
        """執行本階段。實作者只透過 ``context`` 取得 spec 與路徑。"""
        raise NotImplementedError


class DatasetBuildPipeline:
    """依序執行注入的階段（Pipeline / Chain）。"""

    def __init__(self, stages: list[PipelineStage]) -> None:
        """以階段清單建構 pipeline。"""
        self._stages = stages

    def run(self, context: BuildContext) -> None:
        """逐一執行各階段，並輸出起訖 log。"""
        for stage in self._stages:
            logger.info("──── 階段開始：%s ────", stage.name)
            stage.run(context)
            logger.info("──── 階段完成：%s ────", stage.name)
