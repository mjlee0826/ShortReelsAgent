"""把選定片段以亂序命名複製到策展目錄。

亂序命名（clip_01..clip_NN）以 group_id 決定性洗牌，使檔名順序**不對應任何理想排序**（符合
dataset「順序打亂」需求）；同時把 clip_xx ↔ 原始 video_id 的對應寫進 metadata.json 以利追溯。
"""
from __future__ import annotations

import random
import shutil
from pathlib import Path

from ..constants import (
    CLIP_NAME_PAD_WIDTH,
    CLIP_NAME_PREFIX,
    DEFAULT_VIDEO_EXT,
    METADATA_JSON,
)
from ..jsonio import write_models
from ..logging_setup import get_logger
from ..models import ClipCandidate, ClipMetadata, GroupSpec
from ..seeding import stable_seed

logger = get_logger(__name__)


class GroupCurator:
    """單組策展：亂序命名 + 複製 + 寫 metadata。"""

    def curate(
        self, group: GroupSpec, chosen: list[ClipCandidate], curated_dir: Path
    ) -> tuple[list[ClipMetadata], float]:
        """把 ``chosen`` 複製到 ``curated_dir`` 並回傳 (metadata 清單, 總秒數)。"""
        usable = self._filter_downloaded(chosen)
        if not usable:
            return [], 0.0

        curated_dir.mkdir(parents=True, exist_ok=True)
        self._clear_dir(curated_dir)

        # 以 group_id 決定性洗牌：clip 編號與任何理想排序無關
        rng = random.Random(stable_seed(group.group_id))
        shuffled = list(usable)
        rng.shuffle(shuffled)

        metadata: list[ClipMetadata] = []
        total_seconds = 0.0
        for index, candidate in enumerate(shuffled, start=1):
            clip_name = f"{CLIP_NAME_PREFIX}{index:0{CLIP_NAME_PAD_WIDTH}d}"
            ext = Path(candidate.local_path).suffix or DEFAULT_VIDEO_EXT
            dest = curated_dir / f"{clip_name}{ext}"
            shutil.copy2(candidate.local_path, dest)
            metadata.append(self._to_metadata(clip_name, candidate))
            total_seconds += candidate.duration_sec

        write_models(curated_dir / METADATA_JSON, metadata)
        return metadata, total_seconds

    def _filter_downloaded(self, chosen: list[ClipCandidate]) -> list[ClipCandidate]:
        """剔除沒有本機檔案的選取（例如候選檔被刪），並警告。"""
        usable: list[ClipCandidate] = []
        for candidate in chosen:
            if candidate.local_path and Path(candidate.local_path).is_file():
                usable.append(candidate)
            else:
                logger.warning("選取的 %s 缺少本機影片檔，略過", candidate.cache_key)
        return usable

    @staticmethod
    def _clear_dir(curated_dir: Path) -> None:
        """清掉前次策展殘留（讓重跑乾淨）。"""
        for entry in curated_dir.iterdir():
            if entry.is_file():
                entry.unlink()

    @staticmethod
    def _to_metadata(clip_name: str, candidate: ClipCandidate) -> ClipMetadata:
        """由候選組出寫入 dataset 的 metadata。"""
        return ClipMetadata(
            clip_name=clip_name,
            source_platform=candidate.source_platform,
            original_video_id=candidate.video_id,
            page_url=candidate.page_url,
            author_name=candidate.author_name,
            author_url=candidate.author_url,
            license=candidate.license,
            width=candidate.width,
            height=candidate.height,
            duration_sec=candidate.duration_sec,
        )
