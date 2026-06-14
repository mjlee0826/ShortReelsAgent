"""把策展結果打包成版本化、唯讀的 dataset。

輸出目錄（補上 docs 截斷處的結構）：
    <output_dir>/<dataset_version>/
    ├── manifest.json        # 版本、建立時間、各組摘要
    ├── ATTRIBUTION.md       # 逐段出處/作者/URL/授權
    └── groups/<group_id>/
        ├── clips/clip_01.mp4 …
        ├── prompts.json
        └── metadata.json

打包完成後整個目錄 chmod 成唯讀（凍結）；重跑時會先解除唯讀再重建。
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..constants import (
    ATTRIBUTION_MD,
    MANIFEST_JSON,
    METADATA_JSON,
    PROMPTS_JSON,
    READONLY_DIR_MODE,
    READONLY_FILE_MODE,
    WRITABLE_DIR_MODE,
)
from ..jsonio import read_models, write_model, write_models
from ..logging_setup import get_logger
from ..models import (
    ClipMetadata,
    CurationSummary,
    DatasetManifest,
    GroupManifest,
    GroupSpec,
    MediaType,
    PromptVariant,
)
from ..pipeline import BuildContext

logger = get_logger(__name__)

# 解除凍結時暫時給檔案的權限（可讀寫）
_TEMP_WRITABLE_FILE_MODE: int = 0o644


class DatasetPackager:
    """打包與凍結 dataset。"""

    def package(self, context: BuildContext) -> DatasetManifest:
        """組裝版本化 dataset 並凍結；回傳 manifest。"""
        dataset_dir = context.dataset_dir
        self._reset_output(dataset_dir)

        group_manifests: list[GroupManifest] = []
        for group in context.spec.groups:
            manifest = self._package_group(context, group)
            if manifest is not None:
                group_manifests.append(manifest)

        if not group_manifests:
            logger.warning("沒有任何組完成策展，dataset 內容為空（請先 curate）")

        manifest = DatasetManifest(
            dataset_version=context.spec.dataset_version,
            created_at=datetime.now(timezone.utc).isoformat(),
            sources=context.spec.sources,
            group_count=len(group_manifests),
            groups=group_manifests,
        )
        write_model(dataset_dir / MANIFEST_JSON, manifest)
        self._write_attribution(context, dataset_dir, group_manifests)

        self._freeze(dataset_dir)
        logger.info("已打包並凍結 dataset：%s（%d 組）", dataset_dir, len(group_manifests))
        return manifest

    def _package_group(self, context: BuildContext, group: GroupSpec) -> GroupManifest | None:
        """打包單一組；未策展（無 curated metadata）則跳過並回 None。"""
        clip_metadata = read_models(context.curated_metadata_json(group), ClipMetadata)
        if not clip_metadata:
            logger.warning("組 %s：尚未策展（找不到 curated metadata），略過打包", group.group_id)
            return None

        clips_dir = context.group_clips_dir(group)
        clips_dir.mkdir(parents=True, exist_ok=True)

        # 從策展工作目錄複製亂序命名的片段
        curated_dir = context.curated_dir(group)
        for meta in clip_metadata:
            source = self._find_clip_file(curated_dir, meta.clip_name)
            if source is None:
                logger.warning("組 %s：找不到片段檔 %s，略過", group.group_id, meta.clip_name)
                continue
            shutil.copy2(source, clips_dir / source.name)

        # 逐段 metadata 與 prompts 寫進 dataset
        write_models(context.group_dataset_dir(group) / METADATA_JSON, clip_metadata)
        prompts = read_models(context.prompts_json(group), PromptVariant)
        write_models(context.group_dataset_dir(group) / PROMPTS_JSON, prompts)
        if not prompts:
            logger.warning("組 %s：找不到 prompts（請先執行 prompts 階段）", group.group_id)

        summary = self._read_summary(context, group)
        video_count = sum(1 for m in clip_metadata if m.media_type is MediaType.VIDEO)
        image_count = sum(1 for m in clip_metadata if m.media_type is MediaType.IMAGE)
        return GroupManifest(
            group_id=group.group_id,
            theme=group.theme,
            scope=group.scope,
            clip_count=len(clip_metadata),
            video_count=video_count,
            image_count=image_count,
            total_seconds=summary.total_seconds,
            prompt_count=len(prompts),
            curation_mode=summary.curation_mode,
        )

    @staticmethod
    def _read_summary(context: BuildContext, group: GroupSpec) -> CurationSummary:
        """讀策展摘要；缺檔時以中性預設值回傳（不致命）。"""
        path = context.curation_summary_json(group)
        if path.is_file():
            return CurationSummary.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return CurationSummary(curation_mode="unknown", total_seconds=0.0, clip_count=0)

    @staticmethod
    def _find_clip_file(curated_dir: Path, clip_name: str) -> Path | None:
        """在策展目錄找 ``clip_name.*`` 的影片檔。"""
        matches = sorted(curated_dir.glob(f"{clip_name}.*"))
        return matches[0] if matches else None

    def _write_attribution(
        self, context: BuildContext, dataset_dir: Path, group_manifests: list[GroupManifest]
    ) -> None:
        """彙整逐段出處/授權成 ATTRIBUTION.md（Pexels/Pixabay 商用屬性）。"""
        lines = [
            f"# 素材出處與授權（{context.spec.dataset_version}）",
            "",
            "本 dataset 影片素材取自 Pexels / Pixabay，皆可商用。以下逐組逐段列出出處、作者與授權。",
            "",
        ]
        group_by_id = {g.group_id: g for g in context.spec.groups}
        for group_manifest in group_manifests:
            group = group_by_id[group_manifest.group_id]
            lines.append(f"## {group.group_id} — {group.theme}")
            lines.append("")
            clip_metadata = read_models(context.curated_metadata_json(group), ClipMetadata)
            for meta in clip_metadata:
                author = meta.author_name
                if meta.author_url:
                    author = f"[{meta.author_name}]({meta.author_url})"
                lines.append(
                    f"- `{meta.clip_name}` — {meta.source_platform.value} ・ 作者：{author} ・ "
                    f"授權：{meta.license} ・ 來源：{meta.page_url}"
                )
            lines.append("")
        (dataset_dir / ATTRIBUTION_MD).write_text("\n".join(lines), encoding="utf-8")

    # ──────────────────────────── 凍結 / 解凍 ────────────────────────────
    def _reset_output(self, dataset_dir: Path) -> None:
        """重跑時先解除唯讀再刪除舊輸出，確保乾淨重建。"""
        if not dataset_dir.exists():
            return
        logger.info("偵測到既有 dataset 目錄，解除唯讀並重建：%s", dataset_dir)
        # 先把所有目錄與檔案改回可寫，否則唯讀目錄無法刪除其內容
        for root, dirs, files in os.walk(dataset_dir):
            os.chmod(root, WRITABLE_DIR_MODE)
            for name in files:
                os.chmod(os.path.join(root, name), _TEMP_WRITABLE_FILE_MODE)
        shutil.rmtree(dataset_dir)

    @staticmethod
    def _freeze(dataset_dir: Path) -> None:
        """把整個 dataset 目錄設成唯讀（檔 0o444、目錄 0o555）。"""
        # bottom-up：先鎖最深層的檔案與目錄，再鎖上層
        for root, _dirs, files in os.walk(dataset_dir, topdown=False):
            for name in files:
                os.chmod(os.path.join(root, name), READONLY_FILE_MODE)
            os.chmod(root, READONLY_DIR_MODE)
