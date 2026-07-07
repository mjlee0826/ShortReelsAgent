"""
工作站離線攝取本機資料夾 → 建立「本機來源」專案的 CLI 工具 (Facade Pattern)。

當前端網路不穩、不想走瀏覽器 multipart 上傳時,可改在工作站先用 rclone / gdown 把雲端資料夾
抓到本機任一目錄,再用本工具把它「灌」成與 ``POST /projects/from-folder`` 完全一致的本機專案。

一致性保證:本工具不自行硬編任何規則,而是重用後端正規路徑的同一組常數與服務——
``_slugify`` / ``_allocate_unique_name`` / ``_allocate_unique_filename``(命名與去重)、
``MEDIA_EXTENSIONS``(素材過濾)、``RAW_SUBDIR``(分層)、``project_meta_store``(原子寫 meta)、
``user_settings_store``(auto_analyze 快照)、``director_service``(標準化 / Phase 1)。
如此產出的目錄結構、``project_meta.json`` 欄位與背景處理行為,與走 UI 上傳資料夾不會 drift。

用法:
    python -m tools.ingest_local_folder \
        --user-id <Logto sub> \
        --display-name "我的專案" \
        --source /path/to/已下載的雲端資料夾

    # 覆寫是否自動分析(預設沿用該使用者的全域設定,與正規路徑一致):
    #   --analyze        強制建立後立即跑 Phase 1
    #   --no-analyze     只標準化,phase1_status 留 pending,待素材頁手動觸發
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# CLI 進入點也要配置 logging：service 層已全面改 logger，未配置時 INFO 進度訊息會被吞掉
# （本工具自身的使用者輸出仍走 print，屬 CLI 介面而非日誌）
from shared.logging_config import setup_logging

setup_logging()

# 重用正規路徑的命名 / 去重 / meta 欄位邏輯,確保與 from-folder 端點零漂移
from backend.api.projects import (
    _allocate_unique_filename,
    _allocate_unique_name,
    _slugify,
)
from backend.services.director_service import director_service
from backend.services.stores.project_meta_store import project_meta_store
from backend.services.stores.user_settings_store import user_settings_store
from config.app_config import ASSETS_DIR, RAW_SUBDIR
from config.media_formats import MEDIA_EXTENSIONS
from ingestion_engine.models import (
    META_KEY_AUTO_ANALYZE,
    META_KEY_PHASE1_STATUS,
    META_KEY_PHASE1_UPDATED_AT,
    PHASE1_STATUS_PENDING,
    PHASE1_STATUS_SKIPPED,
)

# 程式結束碼:成功 / 來源無有效素材(對應端點的 400)
_EXIT_OK = 0
_EXIT_NO_MEDIA = 1


def _now_iso() -> str:
    """回傳 UTC ISO8601 時間字串(與 projects.py 的 created_at / last_modified 格式一致)。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class IngestRequest:
    """單次離線攝取的請求參數(不可變值物件)。"""

    user_id: str            # 目標使用者(Logto sub);決定專案落在哪個使用者根目錄
    display_name: str       # 專案顯示名;slug 後作為資料夾名
    source_dir: Path        # 已下載到本機的來源資料夾(會遞迴收集其中的媒體檔)
    auto_analyze: Optional[bool] = None  # None=沿用使用者全域設定;True/False=明確覆寫


@dataclass(frozen=True)
class IngestResult:
    """攝取結果摘要(供 CLI 輸出與後續判斷)。"""

    project_name: str       # 實際配置到的(唯一)資料夾名
    project_dir: str        # 專案絕對路徑
    saved_assets: int       # 實際存入 raw/ 的媒體檔數
    auto_analyzed: bool     # 本次是否觸發了 Phase 1(否則僅標準化)


class LocalFolderProjectCreator:
    """
    把本機資料夾建成「本機來源」專案的協調 Facade。

    對齊 ``create_project_from_folder`` 端點的步驟:配置唯一專案名 → 遞迴收集媒體並平鋪進 raw/
    → 寫「不含雲端來源欄位」的 meta → 依 auto_analyze 跑標準化 / Phase 1。雲端來源欄位刻意省略,
    讓專案被視為本機(前端顯「本機」、背景 poller 不挑選)。
    """

    def __init__(self, base_dir: str = ASSETS_DIR) -> None:
        """注入素材根目錄(預設 config 的 ASSETS_DIR);其餘相依沿用模組級單例服務。"""
        self._base_dir = base_dir

    def create(self, request: IngestRequest) -> IngestResult:
        """執行完整攝取流程並回傳結果;來源無任何有效媒體時拋 ValueError(對應端點 400)。"""
        if not request.display_name.strip():
            raise ValueError("專案名稱不能為空")
        if not request.source_dir.is_dir():
            raise ValueError(f"來源資料夾不存在: {request.source_dir}")

        project_name, project_dir = self._allocate_project_dir(request)
        saved = self._copy_media_into_raw(request.source_dir, os.path.join(project_dir, RAW_SUBDIR))
        if saved == 0:
            # 與端點一致:沒有任何受支援媒體就回收空目錄,不留殘骸專案
            shutil.rmtree(project_dir, ignore_errors=True)
            raise ValueError(
                f"來源資料夾內沒有受支援的媒體檔,支援格式: {', '.join(sorted(MEDIA_EXTENSIONS))}"
            )

        auto_analyze = self._resolve_auto_analyze(request)
        self._write_local_meta(project_dir, project_name, request.display_name.strip(), auto_analyze)
        self._run_processing(project_dir, request.user_id, project_name, auto_analyze)

        return IngestResult(
            project_name=project_name,
            project_dir=project_dir,
            saved_assets=saved,
            auto_analyzed=auto_analyze,
        )

    # ── 內部步驟 ──────────────────────────────────────────────────────────────

    def _allocate_project_dir(self, request: IngestRequest) -> tuple[str, str]:
        """以 slug + 唯一化規則配置專案資料夾並建立之,回傳 (專案名, 絕對路徑)。"""
        user_root = os.path.join(self._base_dir, request.user_id)
        os.makedirs(user_root, exist_ok=True)
        name = _allocate_unique_name(user_root, _slugify(request.display_name))
        project_dir = os.path.join(user_root, name)
        os.makedirs(project_dir, exist_ok=True)
        return name, project_dir

    def _copy_media_into_raw(self, source_dir: Path, raw_dir: str) -> int:
        """遞迴收集來源中屬受支援媒體者,平鋪(僅 basename)複製進 raw/,回傳實際存入數。

        對齊端點 ``_store_uploaded_media`` 的語意:依 MEDIA_EXTENSIONS 過濾、不保留子夾結構、
        同名 basename 加序號後綴去重,避免互相覆蓋。
        """
        os.makedirs(raw_dir, exist_ok=True)
        taken_names: set[str] = set()
        saved = 0
        # sorted 讓去重後綴的分配在多次執行間穩定可預期
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            unique_name = _allocate_unique_filename(path.name, taken_names)
            taken_names.add(unique_name)
            shutil.copyfile(path, os.path.join(raw_dir, unique_name))
            saved += 1
        return saved

    def _resolve_auto_analyze(self, request: IngestRequest) -> bool:
        """決定是否自動分析:明確覆寫優先,否則快照該使用者的全域設定(與端點同源)。"""
        if request.auto_analyze is not None:
            return request.auto_analyze
        return user_settings_store.get(request.user_id).auto_analyze_on_create

    def _write_local_meta(
        self, project_dir: str, project_name: str, display_name: str, auto_analyze: bool
    ) -> None:
        """寫入「本機來源」版 project_meta.json:刻意省略所有雲端來源欄位(與端點一致)。"""
        now = _now_iso()
        meta = {
            "name": project_name,
            "display_name": display_name,
            "created_at": now,
            "last_modified": now,
            "asset_count": 0,            # 列表時以 collect_asset_files 即時重算,此處留 0
            "has_blueprint": False,
            # 本機來源:不寫 source / drive_folder_id / sync_status 等,讓前端走本機分支、poller 略過
            META_KEY_PHASE1_STATUS: PHASE1_STATUS_PENDING,
            META_KEY_PHASE1_UPDATED_AT: None,
            META_KEY_AUTO_ANALYZE: auto_analyze,
        }
        project_meta_store.write(project_dir, meta)

    def _run_processing(
        self, project_dir: str, user_id: str, project_name: str, auto_analyze: bool
    ) -> None:
        """同步執行背景處理:auto_analyze 跑完整 Phase 1(內含標準化),否則僅標準化後標 SKIPPED。

        與端點 ``_schedule_local_processing`` 同義,差別在本工具同步執行(CLI 場景無 event loop,
        也方便你直接看到完整 log);run_phase1 內部會先標準化再做感知分析。

        關鍵:關閉自動分析時,標準化完成後須把 phase1_status 由 pending 推進到 SKIPPED(已收斂、
        待手動分析),對齊雲端同步關閉自動分析時的收尾(cloud_ingestion_service ``_ingest_changed``)。
        ``standardize_project`` 刻意不動 phase1_status,若停在 pending,前端 ``useProjectAssets`` 會把
        pending 當「準備中」永遠顯示「正在下載並處理素材」轉圈,既看不到素材也無法手動觸發分析。
        """
        if auto_analyze:
            # run_phase1 自行把 PROCESSING→DONE/FAILED 落地,收斂後前端不再算「準備中」
            director_service.run_phase1(project_name, user_id=user_id, require_success=False)
            return

        director_service.standardize_project(project_name, user_id=user_id)

        def _mark_skipped(meta: dict) -> None:
            """就地把 phase1_status 標為 SKIPPED(已收斂、待手動分析),不碰其餘欄位。"""
            meta[META_KEY_PHASE1_STATUS] = PHASE1_STATUS_SKIPPED
            meta[META_KEY_PHASE1_UPDATED_AT] = _now_iso()

        project_meta_store.update(project_dir, _mark_skipped)


def _parse_args(argv: Optional[list[str]] = None) -> IngestRequest:
    """解析 CLI 參數為 IngestRequest;--analyze / --no-analyze 互斥覆寫自動分析設定。"""
    parser = argparse.ArgumentParser(
        description="把本機資料夾離線攝取成與 UI 上傳資料夾一致的本機來源專案。",
    )
    parser.add_argument("--user-id", required=True, help="目標使用者的 Logto sub")
    parser.add_argument("--display-name", required=True, help="專案顯示名稱")
    parser.add_argument("--source", required=True, type=Path, help="已下載到本機的來源資料夾")
    analyze_group = parser.add_mutually_exclusive_group()
    analyze_group.add_argument(
        "--analyze", dest="auto_analyze", action="store_true", default=None,
        help="建立後立即跑 Phase 1(預設沿用使用者全域設定)",
    )
    analyze_group.add_argument(
        "--no-analyze", dest="auto_analyze", action="store_false",
        help="只標準化,phase1_status 留 pending 待手動觸發",
    )
    args = parser.parse_args(argv)
    return IngestRequest(
        user_id=args.user_id,
        display_name=args.display_name,
        source_dir=args.source,
        auto_analyze=args.auto_analyze,
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 進入點:解析參數 → 執行攝取 → 輸出結果摘要;無有效素材回非零結束碼。"""
    request = _parse_args(argv)
    creator = LocalFolderProjectCreator()
    try:
        result = creator.create(request)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return _EXIT_NO_MEDIA

    print(
        f"✅ 已建立本機專案 '{result.project_name}'：{result.saved_assets} 個素材 → {result.project_dir}\n"
        f"   auto_analyze={result.auto_analyzed}"
        f"（{'已跑 Phase 1' if result.auto_analyzed else '僅標準化,待素材頁手動分析'}）"
    )
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
