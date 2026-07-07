"""
Phase 產物（PHASE1–4 / AI 原版）的集中存取 (Repository Pattern)。

原本 ``director_service`` 內 PHASE1/2/3/4 的路徑組裝 + 讀寫混了三種風格：裸 ``open()+json.load``、
``read_json_tolerant``、``atomic_write_json``——phase2/3 落地甚至是非原子直寫，與「NFS 半寫」的
防護立場自相矛盾。本 store 統一為「容錯讀 + 原子寫」單一出入口：

- **讀**：一律 ``read_json_tolerant``（缺檔 / 半寫 / 損毀回預設，不拋）。
- **寫**：一律 ``atomic_write_json``（唯一 temp + os.replace，併發讀者恆見完整檔）。
- **Phase 1 孤兒過濾**：``read_phase1`` 預設以 ``collect_asset_files`` 的當前素材身分過濾——
  素材經標準化後 raw 身分會被 ``_std`` 取代，殘留舊條目會讓 Phase 4 誤用不可播的 raw（如 HEVC）。
  過去微調路徑漏了這層過濾（與 ``_load_analyzed_assets`` 行為不一致），統一入口後一併修正。
"""
from __future__ import annotations

import os
from typing import Optional

from backend.utils.asset_discovery import (
    PHASE1_METADATA_FILENAME,
    PHASE1_STATUS_FILENAME,
    collect_asset_files,
)
from backend.utils.atomic_json import atomic_write_json, read_json_tolerant
from config.project_artifacts import (
    PHASE2_TEMPLATE_DNA_FILENAME,
    PHASE3_AUDIO_DNA_FILENAME,
    PHASE4_BLUEPRINT_FILENAME,
    PHASE4_BLUEPRINT_AI_ORIGINAL_FILENAME,
)
import logging

logger = logging.getLogger(__name__)


class ProjectArtifactStore:
    """PHASE1–4 產物的路徑組裝 + 容錯讀 + 原子寫（全部無狀態，可安全共用單例）。"""

    # ── 路徑組裝（各 Phase 檔名的唯一組裝點） ─────────────────────────────────

    @staticmethod
    def phase1_metadata_path(project_dir: str) -> str:
        """Phase 1 success-only 感知快取路徑。"""
        return os.path.join(project_dir, PHASE1_METADATA_FILENAME)

    @staticmethod
    def phase1_status_path(project_dir: str) -> str:
        """Phase 1 全狀態檔（UI 用，含 rejected / error）路徑。"""
        return os.path.join(project_dir, PHASE1_STATUS_FILENAME)

    @staticmethod
    def phase2_path(project_dir: str) -> str:
        """Phase 2 範本 DNA 路徑。"""
        return os.path.join(project_dir, PHASE2_TEMPLATE_DNA_FILENAME)

    @staticmethod
    def phase3_path(project_dir: str) -> str:
        """Phase 3 配樂 DNA 路徑。"""
        return os.path.join(project_dir, PHASE3_AUDIO_DNA_FILENAME)

    @staticmethod
    def blueprint_path(project_dir: str) -> str:
        """Phase 4 最終藍圖路徑。"""
        return os.path.join(project_dir, PHASE4_BLUEPRINT_FILENAME)

    @staticmethod
    def ai_original_path(project_dir: str) -> str:
        """Phase 4 不可變 AI 原版（偏好資料飛輪的 AI 起點）路徑。"""
        return os.path.join(project_dir, PHASE4_BLUEPRINT_AI_ORIGINAL_FILENAME)

    # ── Phase 1（讀；merge 寫入邏輯仍在 director_service，見其 _dump_phase1_*） ──

    def read_phase1(self, project_dir: str, only_current_assets: bool = True) -> list:
        """
        容錯讀 Phase 1 感知快取（缺檔 / 損毀回 ``[]``）。

        ``only_current_assets``（預設開）：只留「當前仍存在的素材身分」——raw 被 ``_std`` 取代或
        已刪檔的孤兒條目一律剔除，Phase 4 / 封面挑選不會誤用被取代的身分。
        """
        entries = read_json_tolerant(self.phase1_metadata_path(project_dir), [])
        if not isinstance(entries, list):
            return []
        if not only_current_assets:
            return entries
        valid_ids = set(collect_asset_files(project_dir))
        return [e for e in entries if isinstance(e, dict) and e.get("file", "") in valid_ids]

    def has_phase1(self, project_dir: str) -> bool:
        """Phase 1 快取檔是否存在（precheck 用；內容有效性由 read_phase1 把關）。"""
        return os.path.exists(self.phase1_metadata_path(project_dir))

    # ── Phase 2 / 3（範本 DNA / 配樂 DNA） ────────────────────────────────────

    def read_phase2(self, project_dir: str) -> Optional[dict]:
        """容錯讀範本 DNA；缺檔 / 損毀回 None（視同無範本）。"""
        data = read_json_tolerant(self.phase2_path(project_dir), None)
        return data if isinstance(data, dict) else None

    def write_phase2(self, project_dir: str, template_dna: dict) -> None:
        """原子落地範本 DNA。"""
        atomic_write_json(self.phase2_path(project_dir), template_dna)
        logger.info(f"💾 [Dump] 範本 DNA 已儲存至 {self.phase2_path(project_dir)}")

    def read_phase3(self, project_dir: str) -> Optional[dict]:
        """容錯讀配樂 DNA；缺檔 / 損毀回 None（視同無配樂）。"""
        data = read_json_tolerant(self.phase3_path(project_dir), None)
        return data if isinstance(data, dict) else None

    def write_phase3(self, project_dir: str, audio_dna: dict) -> None:
        """原子落地配樂 DNA。"""
        atomic_write_json(self.phase3_path(project_dir), audio_dna)
        logger.info(f"💾 [Dump] 配樂 DNA 已儲存至 {self.phase3_path(project_dir)}")

    # ── Phase 4（最終藍圖 / AI 原版） ─────────────────────────────────────────

    def read_blueprint(self, project_dir: str) -> Optional[dict]:
        """容錯讀最終藍圖；缺檔 / 半寫 / 損毀回 None（視同尚未生成）。"""
        data = read_json_tolerant(self.blueprint_path(project_dir), None)
        return data if isinstance(data, dict) and data else None

    def write_blueprint(self, project_dir: str, blueprint: dict) -> None:
        """原子落地最終藍圖（生成與編輯器自動儲存共用）。"""
        atomic_write_json(self.blueprint_path(project_dir), blueprint)
        logger.info(f"💾 [Dump] 最終劇本藍圖已儲存至 {self.blueprint_path(project_dir)}")

    def has_blueprint(self, project_dir: str) -> bool:
        """最終藍圖檔是否存在（project_meta 的 has_blueprint 快取欄位用）。"""
        return os.path.exists(self.blueprint_path(project_dir))

    def write_ai_original(self, project_dir: str, blueprint: dict) -> None:
        """（覆）寫不可變 AI 原版：初次生成的 AI 起點；微調與 autosave 不碰它。"""
        atomic_write_json(self.ai_original_path(project_dir), blueprint)


# 模組級單例（與其他 store 一致的使用慣例）
artifact_store = ProjectArtifactStore()
