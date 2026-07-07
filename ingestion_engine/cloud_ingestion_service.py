"""
雲端攝取同步協調層 (Facade / Service Pattern)。

把單一雲端來源 project 的「列檔 → 比對素材簽章 → 增量下載 → 觸發 Phase 1 → 寫回同步狀態」
整條流程收斂在此。雲端來源與同步狀態折進該 project 的 `project_meta.json`（不另建註冊檔），
本層直接讀寫該檔。

對內以注入的 adapter（雲端存取）與 phase1_runner（Phase 1 觸發 callback）協作；刻意不 import
backend，避免 ingestion_engine 與 backend 互相 import 形成循環依賴（接線在 ingestion_provider）。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import threading
from typing import Callable, ContextManager, Optional

from config.app_config import ASSETS_DIR, RAW_SUBDIR
from config.project_artifacts import PROJECT_META_FILENAME
from ingestion_engine.cloud_storage_adapter import CloudStorageAdapter
from ingestion_engine.exceptions import (
    Phase1DeferredError,
    RemoteAccessError,
    RemoteAuthError,
)
from ingestion_engine.models import (
    META_KEY_AUTO_ANALYZE,
    META_KEY_DRIVE_FOLDER_ID,
    META_KEY_LAST_SIGNATURE,
    META_KEY_LAST_SYNC_ERROR,
    META_KEY_LAST_SYNCED_AT,
    META_KEY_PHASE1_STATUS,
    META_KEY_PHASE1_UPDATED_AT,
    META_KEY_REMOTE_MANIFEST,
    META_KEY_SOURCE,
    META_KEY_SYNC_STATUS,
    PHASE1_STATUS_DONE,
    PHASE1_STATUS_FAILED,
    PHASE1_STATUS_INGESTING,
    PHASE1_STATUS_SKIPPED,
    RemoteEntry,
    SOURCE_GDRIVE,
    SYNC_STATUS_ACTIVE,
    SYNC_STATUS_ERROR,
    SYNC_STATUS_PAUSED_AUTH,
    SyncReport,
    _now_iso,
)
import logging

logger = logging.getLogger(__name__)

# Phase 1 觸發 callback 型別：吃 (user_id, project_name)，對該本地 project 跑 Phase 1；失敗時 raise。
Phase1Runner = Callable[[str, str], None]
# 衍生產物清理 callback 型別：吃 (user_id, project_name)，把該 project 內「對不上磁碟的衍生產物」
# （孤兒 standardized 檔、phase1 metadata/status、逐檔策略）清掉。實作在 backend 並以注入避免循環 import。
ArtifactPruner = Callable[[str, str], None]
# ingest 執行護衛 callback 型別：吃 (user_id, project_name) 回 context manager。進入時取得該 project
# 的 Phase 1 執行鎖（標 ingesting），讓「下載 + 標準化 + 自動分析」整段與素材頁/編輯頁的手動分析
# 互斥；搶不到鎖（前景正在分析）則 raise Phase1DeferredError。離開時釋放鎖。實作在 backend 並注入。
IngestGuard = Callable[[str, str], ContextManager]
# 標準化 callback 型別：吃 (user_id, project_name)，只對該 project 做 raw→standardized 標準化
# （不跑感知分析）。供「關閉自動分析」時也先穩定素材身分。實作在 backend 並以注入避免循環 import。
StandardizeRunner = Callable[[str, str], None]


class CloudIngestionService:
    """單一雲端來源 project 的同步協調 Facade（Drive 公開資料夾 → 本地素材 + Phase 1）。"""

    def __init__(
        self,
        adapter: CloudStorageAdapter,
        phase1_runner: Phase1Runner,
        artifact_pruner: ArtifactPruner,
        ingest_guard: IngestGuard,
        standardize_runner: StandardizeRunner,
        base_dir: str = ASSETS_DIR,
    ):
        """注入雲端 adapter、Phase 1 觸發 / 衍生產物清理 / ingest 護衛 / 標準化 callback；base_dir 為素材根目錄。"""
        self._adapter = adapter
        self._phase1_runner = phase1_runner
        self._prune_artifacts = artifact_pruner
        # ingest 護衛(取/放 Phase 1 執行鎖,標 ingesting)與只做標準化的 callback;見上方型別註解
        self._ingest_guard = ingest_guard
        self._standardize = standardize_runner
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

        # 每檔遠端指紋（size + mod_time）：size 抓得到一般替換，mod_time 補抓「同名同大小換內容」
        remote_fp = self._remote_fingerprints(media)
        signature = self._signature_of(remote_fp)
        # DONE 與 SKIPPED 同視為「已收斂」：前者已分析、後者依設定刻意不自動分析；
        # 二者搭配簽章未變即無需再動，避免關閉自動分析的專案被 poller 每輪重複下載 / 觸發。
        phase1_settled = meta.get(META_KEY_PHASE1_STATUS) in (
            PHASE1_STATUS_DONE, PHASE1_STATUS_SKIPPED,
        )
        unchanged = signature == meta.get(META_KEY_LAST_SIGNATURE) and phase1_settled
        if unchanged:
            return self._mark_synced(project_dir, report)

        # 有變動的處理(汰除舊檔 → 下載 → 標準化 / 分析)整段需與素材頁/編輯頁的手動 Phase 1 互斥:
        # 進入 ingest 護衛取得該 project 的 Phase 1 執行鎖(標 ingesting),讓使用者無法在素材尚未下載/
        # 標準化完成時就自己跑 Phase 1。搶不到鎖(前景正在分析)即 raise Phase1DeferredError → 本輪
        # 略過、保留狀態待下輪重試;離開時釋放鎖。取鎖順序恆為「同步鎖 → Phase 1 鎖」,無死鎖。
        try:
            with self._ingest_guard(user_id, project_name):
                return self._ingest_changed(
                    user_id, project_name, project_dir, meta, remote_fp, signature, report
                )
        except Phase1DeferredError as exc:
            # 前景已有 Phase 1 在跑:本輪不下載/不分析、不前進簽章,保留狀態讓下輪 poller 重試
            logger.info(f"[CloudIngestion] {exc}")
            return self._mark_synced(project_dir, report)

    def _ingest_changed(
        self,
        user_id: str,
        project_name: str,
        project_dir: str,
        meta: dict,
        remote_fp: dict[str, str],
        signature: str,
        report: SyncReport,
    ) -> SyncReport:
        """
        在已持有 Phase 1 執行鎖(ingesting)下處理「偵測到素材變動」:
        汰除舊檔 → 下載 → 一律標準化 →（依設定）跑 Phase 1 或標 SKIPPED。

        進入即把 phase1_status 標 INGESTING(下載 / 標準化階段;auto-on/off 皆然):驅動素材頁與專案
        卡片顯示「處理素材中」,且中途崩潰時下輪 poller 會因非「已收斂」而重抓重做(idempotent),狀態
        自癒。標準化(含)以前都維持 INGESTING;auto-on 待標準化完成、真正進入感知分析前才翻成
        PROCESSING(分析中)並建立可追進度的 job,讓兩階段在 UI 上可區分(標準化期間持續顯示轉圈,
        不會因 job_id 提前落地而被前端誤判為分析中)。
        """
        # 進入處理即標 INGESTING:下載 / 標準化共用此狀態,前端據此顯示「處理素材中」轉圈
        self._patch_meta(project_dir, {META_KEY_PHASE1_STATUS: PHASE1_STATUS_INGESTING})

        # 對齊遠端：把「被移除 / 被同名替換」的本地素材連同其衍生產物先汰除，
        # 確保 changed 之後會重抓重轉重析、removed 徹底消失（download 只增不刪，故須在此主動刪）。
        self._evict_stale_assets(user_id, project_name, project_dir, meta, remote_fp, report)

        # 有新增／替換素材：先下載到 raw/（原始檔分層；adapter 會自建目標目錄）
        # 「已存在且同大小跳過」的增量判斷看 raw/
        folder_id = meta[META_KEY_DRIVE_FOLDER_ID]
        raw_dir = os.path.join(project_dir, RAW_SUBDIR)
        try:
            self._adapter.download_folder(folder_id, raw_dir)
        except RemoteAuthError as exc:
            return self._pause_for_auth(project_dir, report, exc)
        except RemoteAccessError as exc:
            return self._fail_sync(project_dir, report, exc)
        report.downloaded = True
        # 下載完成 → 磁碟已對齊遠端，先落地新指紋（與 signature 解耦：指紋記「磁碟已同步到哪」、
        # signature 記「已分析到哪」）。如此 Phase 1 失敗下輪重試時不會把剛抓好的檔當 changed 再刪一次。
        self._patch_meta(project_dir, {META_KEY_REMOTE_MANIFEST: remote_fp})

        # 一律先標準化(仍維持 INGESTING):把新下載的 .mov/.heic 等轉成 _std 身分穩定下來,讓素材身分
        # 穩定、前端可預覽,且日後「開始生成」不因身分漂移而漏跑。auto-on/off 皆走此步。
        #
        # 關鍵:標準化必須在「翻成 PROCESSING / 建立可追進度的分析 job 之前」做。標準化期間尚無 _std
        # 可預覽(list_assets 隱藏待標準化的 raw → 素材清單為空)、也無 per-asset 進度可看,素材頁應持續
        # 顯示「處理素材中」轉圈。若提前翻成 PROCESSING 並由 _phase1_runner 在 job 建立當下 publish
        # 出 active_job_id,前端(重整後查 phase1-progress)會誤判分析已開始而 attach,把轉圈換成「空格線
        # + 0/0 進度條」——正是 auto 開啟時重整素材頁轉圈消失的成因。
        self._standardize(user_id, project_name)

        # 使用者設定「建立後不自動分析」：標準化已完成,只刻意略過感知分析,待其到素材頁手動觸發。
        # 標 SKIPPED + 更新簽章,讓本輪與後續 poller 都視為已收斂、不再重複觸發。缺鍵預設 True,
        # 使本欄位導入前建立的舊專案維持原本自動分析行為（零破壞）。
        if not meta.get(META_KEY_AUTO_ANALYZE, True):
            self._patch_meta(project_dir, {
                META_KEY_PHASE1_STATUS: PHASE1_STATUS_SKIPPED,
                META_KEY_PHASE1_UPDATED_AT: _now_iso(),
                META_KEY_LAST_SIGNATURE: signature,
            })
            return self._mark_synced(project_dir, report)

        # 自動分析：標準化已完成(素材身分穩定、前端可預覽),交給 Phase 1 跑感知分析。
        # PROCESSING(分析中)改由 run_phase1 進入分析時自行標記(四個進入點統一擁有 PROCESSING→DONE);
        # 本層刻意不再預先標 PROCESSING——否則「簽章變動但無待分析素材」(如純刪檔)時 run_phase1 會
        # 早退、不標任何狀態,卡片將卡在 PROCESSING;該收斂情形改由本層收尾統一標 DONE(見下方成功分支)。
        # 失敗只標 failed、保留舊簽章供下輪重試,不視為同步失敗。鎖已由 ingest 護衛持有,
        # _phase1_runner 不再自行取鎖（避免重入）。INGESTING(處理素材中)→ PROCESSING(分析中)兩階段在 UI 上區分。
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

    def _evict_stale_assets(
        self,
        user_id: str,
        project_name: str,
        project_dir: str,
        meta: dict,
        remote_fp: dict[str, str],
        report: SyncReport,
    ) -> None:
        """
        汰除「相對上次同步被移除 / 被同名替換」的素材：先刪本地 raw 原始檔，再清其衍生產物。

        以上次同步落地的指紋（META_KEY_REMOTE_MANIFEST）對比本次遠端指紋：
        - removed：上次有、這次沒 → 整個素材已從雲端刪除，本地應一併移除。
        - changed：兩邊都有但指紋不同（含同名同大小換內容）→ 內容已變，刪掉舊 raw 讓 download 重抓新檔。
        raw 由本層直接刪（本層擁有 raw 層）；standardized / phase1 metadata/status / 逐檔策略等衍生產物
        交給注入的 clean callback 對齊磁碟真相清除。清除失敗只記錄、不中斷主同步（最多殘留孤兒，
        不應反過來卡住下載 / 分析）。
        """
        previous_fp = meta.get(META_KEY_REMOTE_MANIFEST) or {}
        removed = set(previous_fp) - set(remote_fp)
        changed = {name for name in remote_fp if name in previous_fp and previous_fp[name] != remote_fp[name]}
        stale = removed | changed
        if not stale:
            return

        self._delete_raw_files(os.path.join(project_dir, RAW_SUBDIR), stale)
        # raw 刪完後，被替換素材的 standardized 衍生檔已成孤兒：此時 prune 才能正確把它一併清掉
        try:
            self._prune_artifacts(user_id, project_name)
        except Exception as exc:  # noqa: BLE001 - 清除衍生產物失敗不應中斷同步主流程
            logger.warning(f"⚠️ [CloudIngestion] 清除衍生產物失敗（{project_name}）: {exc}")
            report.errors.append(f"清除衍生產物失敗: {exc}")

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
        logger.warning(f"⚠️ [CloudIngestion] 授權失效，暫停專案同步（{report.project_name}）：{exc}")
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
        logger.warning(f"⚠️ [CloudIngestion] 同步錯誤（暫時性，下輪重試）（{report.project_name}）：{exc}")
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
        meta_path = os.path.join(project_dir, PROJECT_META_FILENAME)
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _patch_meta(self, project_dir: str, fields: dict) -> None:
        """讀取既有 project_meta.json，更新指定欄位後以唯一 temp+rename 原子寫回；meta 不存在則略過。"""
        meta = self._read_meta(project_dir)
        if meta is None:
            return
        meta.update(fields)
        meta_path = os.path.join(project_dir, PROJECT_META_FILENAME)
        # 唯一 temp 檔:poller 與後端同進程寫同一檔,固定共用 .tmp 會被另一寫者截斷而換入損毀內容
        fd, tmp_path = tempfile.mkstemp(dir=project_dir, prefix=f"{PROJECT_META_FILENAME}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, meta_path)
        except OSError:
            # metadata 更新失敗不應中斷同步主流程;清掉殘留 temp 再返回
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
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
    def _remote_fingerprints(media_files: list[RemoteEntry]) -> dict[str, str]:
        """回傳 {檔名: "size:mod_time"} 的每檔遠端指紋；size 抓一般替換、mod_time 抓同名同大小換內容。"""
        return {f.name: f"{f.size}:{f.mod_time}" for f in media_files}

    @staticmethod
    def _signature_of(remote_fp: dict[str, str]) -> str:
        """以每檔指紋集合算整體簽章；變動代表有新增／移除／替換素材，需重新同步。"""
        items = sorted(f"{name}:{fingerprint}" for name, fingerprint in remote_fp.items())
        return hashlib.sha1("|".join(items).encode("utf-8")).hexdigest()

    @staticmethod
    def _delete_raw_files(raw_dir: str, names: set[str]) -> None:
        """刪除 raw/ 下指定檔名的素材（容忍不存在 / 刪除失敗，清理用不應掩蓋主流程）。"""
        for name in names:
            with contextlib.suppress(OSError):
                os.remove(os.path.join(raw_dir, name))
