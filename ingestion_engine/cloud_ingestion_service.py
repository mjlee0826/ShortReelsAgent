"""
雲端攝取同步協調層 (Facade / Service Pattern)。

把單一雲端來源 project 的「列檔 → 比對素材簽章 → 增量下載 → 觸發 Phase 1 → 寫回同步狀態」
整條流程收斂在此。雲端來源與同步狀態折進該 project 的 `project_meta.json`（不另建註冊檔），
本層直接讀寫該檔。

對內以注入的 adapter（雲端存取）與 phase1_runner（Phase 1 觸發 callback）協作；刻意不 import
backend，避免 ingestion_engine 與 backend 互相 import 形成循環依賴（接線在 ingestion_provider）。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Callable, Optional

from config.app_config import ASSETS_DIR
from ingestion_engine.cloud_storage_adapter import CloudStorageAdapter
from ingestion_engine.exceptions import RemoteAccessError, RemoteAuthError
from ingestion_engine.models import (
    META_KEY_DRIVE_FOLDER_ID,
    META_KEY_LAST_SIGNATURE,
    META_KEY_LAST_SYNC_ERROR,
    META_KEY_LAST_SYNCED_AT,
    META_KEY_PHASE1_STATUS,
    META_KEY_PHASE1_UPDATED_AT,
    META_KEY_SOURCE,
    META_KEY_SYNC_STATUS,
    PHASE1_STATUS_DONE,
    PHASE1_STATUS_FAILED,
    PHASE1_STATUS_PROCESSING,
    RemoteEntry,
    SOURCE_GDRIVE,
    SYNC_STATUS_ACTIVE,
    SYNC_STATUS_ERROR,
    SYNC_STATUS_PAUSED_AUTH,
    SyncReport,
    _now_iso,
)

# Phase 1 觸發 callback 型別：吃 (user_id, project_name)，對該本地 project 跑 Phase 1；失敗時 raise。
Phase1Runner = Callable[[str, str], None]

_META_FILENAME = "project_meta.json"


class CloudIngestionService:
    """單一雲端來源 project 的同步協調 Facade（Drive 公開資料夾 → 本地素材 + Phase 1）。"""

    def __init__(
        self,
        adapter: CloudStorageAdapter,
        phase1_runner: Phase1Runner,
        base_dir: str = ASSETS_DIR,
    ):
        """注入雲端 adapter 與 Phase 1 觸發 callback；base_dir 為素材根目錄。"""
        self._adapter = adapter
        self._phase1_runner = phase1_runner
        self._base_dir = base_dir
        # 每個 project 一把鎖，序列化 poller 與手動 sync 對同一 project 的並發同步
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ── 公開方法 ──────────────────────────────────────────────────────────────

    def parse_source(self, source_url: str) -> str:
        """委派 adapter 把來源 URL 解析為資料夾 locator（供端點建 project 前取得）。"""
        return self._adapter.parse_source(source_url)

    def sync_project(self, user_id: str, project_name: str) -> SyncReport:
        """
        同步單一雲端來源 project：偵測素材變動 → 增量下載 → 觸發 Phase 1 → 更新同步狀態。

        授權失效只暫停「本」project（不 raise，讓 poller 續跑其他 project）；其餘雲端錯誤標 error
        下輪重試；Phase 1 失敗只標 failed 不更新簽章（供下輪重試），不影響同步本身成功。
        非雲端來源或缺 folder ID 的 project 直接略過。
        """
        project_dir = self._project_dir(user_id, project_name)
        with self._lock_for(project_dir):
            meta = self._read_meta(project_dir)
            if meta is None:
                raise KeyError(f"找不到 project: {project_name}")

            report = SyncReport(
                project_name=project_name,
                sync_status=meta.get(META_KEY_SYNC_STATUS, SYNC_STATUS_ACTIVE),
            )
            if meta.get(META_KEY_SOURCE) != SOURCE_GDRIVE:
                return report  # 非雲端來源 project，不做同步

            folder_id = meta.get(META_KEY_DRIVE_FOLDER_ID)
            if not folder_id:
                return self._fail_sync(project_dir, report, "project_meta 缺少 drive_folder_id")

            try:
                media = self._adapter.list_files(folder_id)
            except RemoteAuthError as exc:
                return self._pause_for_auth(project_dir, report, exc)
            except RemoteAccessError as exc:
                return self._fail_sync(project_dir, report, exc)

            return self._reconcile(user_id, project_name, project_dir, meta, media, report)

    # ── 同步主邏輯 ────────────────────────────────────────────────────────────

    def _reconcile(
        self,
        user_id: str,
        project_name: str,
        project_dir: str,
        meta: dict,
        media: list[RemoteEntry],
        report: SyncReport,
    ) -> SyncReport:
        """比對素材簽章決定是否下載 + 重跑 Phase 1；無變動則僅更新同步時間。"""
        if not media:
            return self._mark_synced(project_dir, report)  # 空資料夾：等有素材再處理

        signature = self._asset_signature(media)
        unchanged = (
            signature == meta.get(META_KEY_LAST_SIGNATURE)
            and meta.get(META_KEY_PHASE1_STATUS) == PHASE1_STATUS_DONE
        )
        if unchanged:
            return self._mark_synced(project_dir, report)

        # 有新增／替換素材：先下載（下載失敗不應留下 processing 假象）
        folder_id = meta[META_KEY_DRIVE_FOLDER_ID]
        try:
            self._adapter.download_folder(folder_id, project_dir)
        except RemoteAuthError as exc:
            return self._pause_for_auth(project_dir, report, exc)
        except RemoteAccessError as exc:
            return self._fail_sync(project_dir, report, exc)
        report.downloaded = True

        # 觸發 Phase 1：失敗只標 failed、保留舊簽章供下輪重試，不視為同步失敗
        self._patch_meta(project_dir, {META_KEY_PHASE1_STATUS: PHASE1_STATUS_PROCESSING})
        try:
            self._phase1_runner(user_id, project_name)
        except Exception as exc:  # noqa: BLE001 - Phase 1 任何失敗都只隔離此 project
            self._patch_meta(project_dir, {
                META_KEY_PHASE1_STATUS: PHASE1_STATUS_FAILED,
                META_KEY_PHASE1_UPDATED_AT: _now_iso(),
            })
            report.errors.append(f"Phase 1 失敗: {exc}")
            return self._mark_synced(project_dir, report)

        report.phase1_ran = True
        self._patch_meta(project_dir, {
            META_KEY_PHASE1_STATUS: PHASE1_STATUS_DONE,
            META_KEY_PHASE1_UPDATED_AT: _now_iso(),
            META_KEY_LAST_SIGNATURE: signature,
        })
        return self._mark_synced(project_dir, report)

    # ── 同步收尾 ──────────────────────────────────────────────────────────────

    def _mark_synced(self, project_dir: str, report: SyncReport) -> SyncReport:
        """同步成功收尾：回 active、清錯、更新同步時間並持久化。"""
        self._patch_meta(project_dir, {
            META_KEY_SYNC_STATUS: SYNC_STATUS_ACTIVE,
            META_KEY_LAST_SYNC_ERROR: None,
            META_KEY_LAST_SYNCED_AT: _now_iso(),
        })
        report.sync_status = SYNC_STATUS_ACTIVE
        return report

    def _pause_for_auth(self, project_dir: str, report: SyncReport, exc: object) -> SyncReport:
        """授權失效：暫停此 project 同步、記錄錯誤並持久化（其他 project 不受影響）。"""
        self._patch_meta(project_dir, {
            META_KEY_SYNC_STATUS: SYNC_STATUS_PAUSED_AUTH,
            META_KEY_LAST_SYNC_ERROR: str(exc),
            META_KEY_LAST_SYNCED_AT: _now_iso(),
        })
        report.sync_status = SYNC_STATUS_PAUSED_AUTH
        report.errors.append(str(exc))
        return report

    def _fail_sync(self, project_dir: str, report: SyncReport, exc: object) -> SyncReport:
        """非授權類雲端錯誤：標 error（暫時性，下輪重試）並持久化。"""
        self._patch_meta(project_dir, {
            META_KEY_SYNC_STATUS: SYNC_STATUS_ERROR,
            META_KEY_LAST_SYNC_ERROR: str(exc),
            META_KEY_LAST_SYNCED_AT: _now_iso(),
        })
        report.sync_status = SYNC_STATUS_ERROR
        report.errors.append(str(exc))
        return report

    # ── meta 讀寫 ─────────────────────────────────────────────────────────────

    def _read_meta(self, project_dir: str) -> Optional[dict]:
        """讀取 project_meta.json；不存在或損毀回 None。"""
        meta_path = os.path.join(project_dir, _META_FILENAME)
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _patch_meta(self, project_dir: str, fields: dict) -> None:
        """讀取既有 project_meta.json，更新指定欄位後以 temp+rename 原子寫回；meta 不存在則略過。"""
        meta = self._read_meta(project_dir)
        if meta is None:
            return
        meta.update(fields)
        meta_path = os.path.join(project_dir, _META_FILENAME)
        tmp_path = f"{meta_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, meta_path)
        except OSError:
            # metadata 更新失敗不應中斷同步主流程
            return

    # ── 純函式工具 ────────────────────────────────────────────────────────────

    def _project_dir(self, user_id: str, project_name: str) -> str:
        """取得本地 project 資料夾絕對路徑。"""
        return os.path.join(self._base_dir, user_id, project_name)

    def _lock_for(self, project_dir: str) -> threading.Lock:
        """取得（必要時建立）某 project 的同步鎖。"""
        with self._locks_guard:
            lock = self._locks.get(project_dir)
            if lock is None:
                lock = threading.Lock()
                self._locks[project_dir] = lock
        return lock

    @staticmethod
    def _asset_signature(media_files: list[RemoteEntry]) -> str:
        """以（檔名+大小）集合算簽章；變動代表有新增／替換素材，需重跑 Phase 1。"""
        items = sorted(f"{f.name}:{f.size}" for f in media_files)
        return hashlib.sha1("|".join(items).encode("utf-8")).hexdigest()
