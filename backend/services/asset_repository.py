"""
素材狀態與策略儲存庫 (Repository Pattern)。

封裝 Asset Management UI 需要的素材檢視:把「磁碟上的素材檔」「Phase 1 全狀態檔」「逐檔策略 /
dirty 標記(折進 project_meta.json)」「縮圖」這幾個來源 join 成單一 ``AssetView`` 清單。
逐檔策略與 dirty 比照雲端同步狀態,折進 project_meta.json,不另建註冊檔。
"""
from __future__ import annotations

import json
import os
from enum import Enum
from typing import Optional
from urllib.parse import quote

from pydantic import BaseModel

from backend.services.asset_discovery import (
    PHASE1_METADATA_FILENAME,
    PHASE1_STATUS_FILENAME,
    collect_asset_files,
    to_abs_path,
)
from backend.services.project_meta_store import project_meta_store
from backend.services.thumbnail_service import ThumbnailService
from config.app_config import ASSETS_DIR, DEFAULT_BACKEND_URL
from media_processor.pipeline.context import derive_media_kind

# project_meta.json 內逐檔策略 / dirty 相關欄位鍵(具名常數,避免散落 magic string)
# 鍵一律為素材身分 relpath(如 raw/photo.jpg),與 status / metadata / blueprint clip_id 全程一致
META_KEY_ASSET_STRATEGIES = "asset_strategies"  # {relpath: "simple"|"complex"}
META_KEY_DIRTY_ASSETS = "dirty_assets"          # 策略變更後待重跑 Phase 1 的 relpath 清單
# {relpath: 上次 Phase 1 分析時所用策略};供「策略改回上次分析值即不再 dirty」的回退判斷
META_KEY_ANALYZED_STRATEGIES = "analyzed_strategies"

# 素材尚未被 Phase 1 分析過(全狀態檔內查無此檔)時的 UI 狀態
ASSET_STATUS_UNPROCESSED = "unprocessed"

# 後端對外位址改用 config.app_config.DEFAULT_BACKEND_URL(見頂部 import),消除散落的同字面量

# 副檔名 → MIME(供詳情前端決定 <img>/<video> 呈現與 HEIC 後備;集中於此避免 magic string)
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
}


class AssetStrategy(str, Enum):
    """逐檔感知策略(API 契約用,與 media_processor 的列舉解耦)。"""

    SIMPLE = "simple"   # 本地 Qwen 全局分析
    COMPLEX = "complex"  # Gemini 深度分析


class AssetView(BaseModel):
    """單一素材給前端網格的檢視模型 (Value Object)。"""

    path: str                                # 素材身分 relpath(如 raw/photo.jpg);前端識別 / API 鍵
    filename: str                            # basename(純顯示用;含 / 的 path 不適合直接顯示)
    media_kind: str                          # "image" | "video"
    status: str                              # unprocessed | success | rejected | error
    strategy: str = AssetStrategy.SIMPLE.value
    dirty: bool = False                      # 策略已變更、待下次「開始生成」重跑
    technical_score: Optional[float] = None
    reason: Optional[str] = None             # rejected 時的原因(技術分過低)
    error: Optional[str] = None              # error 時的錯誤訊息
    thumbnail_url: Optional[str] = None
    size_bytes: int = 0
    modified_at: str = ""


class AssetDetailView(BaseModel):
    """單一素材的完整詳情檢視 (Value Object)。

    在列表用的 ``AssetView`` 之上,補上「未裁切原始媒體 URL」與 Phase 1 完整感知 metadata,
    供前端詳情彈窗呈現全圖 / 完整影片與分區資訊。``metadata`` 對 rejected / error /
    unprocessed 素材為 None(這些素材本就沒有 success metadata,前端走狀態說明分支)。
    """

    asset: AssetView                          # 重用列表檢視(狀態 / 策略 / dirty / 縮圖 / 技術分)
    media_url: Optional[str] = None           # /static 原始媒體完整 URL(未裁切全圖 / 完整影片)
    media_mime: Optional[str] = None          # 例 image/jpeg、video/mp4、image/heic(前端據此決定呈現)
    metadata: Optional[dict] = None           # phase1_assets_metadata.json 該檔的 metadata 區塊(原樣)
    metadata_kind: Optional[str] = None       # "image" | "video"(metadata 結構辨識用)


class AssetRepository:
    """讀寫素材檢視 / 策略 / dirty 的儲存庫;縮圖產生委派給注入的 ThumbnailService。"""

    def __init__(
        self,
        assets_dir: str = ASSETS_DIR,
        thumbnail_service: Optional[ThumbnailService] = None,
        backend_url: Optional[str] = None,
    ):
        """設定素材根目錄、注入縮圖服務(預設自建),並記錄後端對外位址供組原始媒體 URL。"""
        self._assets_dir = assets_dir
        self._thumbnails = thumbnail_service or ThumbnailService()
        # 與 ThumbnailService 同一套讀法:優先參數 → 環境變數 BACKEND_URL → 預設 localhost
        self._backend_url = backend_url or os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL)

    # ── 路徑與 JSON 讀寫 ─────────────────────────────────────────────────────

    def _project_dir(self, user_id: str, project: str) -> str:
        """取得使用者某專案的資料夾路徑;不存在則拋 FileNotFoundError。"""
        path = os.path.join(self._assets_dir, user_id, project)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"找不到專案: {project}")
        return path

    @staticmethod
    def _read_meta(project_dir: str) -> dict:
        """讀取 project_meta.json;缺檔 / 無法復原回空 dict(讀-改-寫時保留既有欄位)。委派容錯讀取。"""
        return project_meta_store.read(project_dir) or {}

    @staticmethod
    def _read_status_map(project_dir: str) -> dict:
        """讀取 Phase 1 全狀態檔(鍵為檔名);不存在回空 dict(全部視為未處理)。"""
        status_path = os.path.join(project_dir, PHASE1_STATUS_FILENAME)
        if not os.path.exists(status_path):
            return {}
        with open(status_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _read_metadata_map(project_dir: str) -> dict:
        """
        讀取 Phase 1 success-only 完整 metadata 檔,轉成「relpath 身分 → 該筆紀錄」對照。

        檔內為 list(每筆含 relpath ``file`` 與 ``metadata``);``file`` 即素材身分,直接當鍵與
        ``AssetView.path`` 對齊。不存在回空 dict(全部視為無 metadata)。
        """
        metadata_path = os.path.join(project_dir, PHASE1_METADATA_FILENAME)
        if not os.path.exists(metadata_path):
            return {}
        with open(metadata_path, "r", encoding="utf-8") as f:
            records = json.load(f)
        return {rec["file"]: rec for rec in records if rec.get("file")}

    # ── 對外操作 ─────────────────────────────────────────────────────────────

    def list_assets(self, user_id: str, project: str) -> list[AssetView]:
        """
        列出某專案的所有素材檢視:磁碟素材檔為主,join 全狀態檔取狀態、meta 取策略 / dirty、
        並順手 lazy 補產縮圖。查無狀態的素材一律標 ``unprocessed``。
        """
        project_dir = self._project_dir(user_id, project)
        meta = self._read_meta(project_dir)
        strategies = meta.get(META_KEY_ASSET_STRATEGIES, {})
        dirty_set = set(meta.get(META_KEY_DIRTY_ASSETS, []))
        status_map = self._read_status_map(project_dir)

        views: list[AssetView] = []
        for relpath in collect_asset_files(project_dir):
            file_path = to_abs_path(project_dir, relpath)
            filename = os.path.basename(relpath)
            try:
                media_kind = derive_media_kind(relpath)
            except ValueError:
                # collect_asset_files 已過濾;防呆跳過
                continue
            # status / strategy / dirty 一律以 relpath 身分為鍵
            status_entry = status_map.get(relpath, {})
            stat = os.stat(file_path)
            views.append(AssetView(
                path=relpath,
                filename=filename,
                media_kind=media_kind.value,
                status=status_entry.get("status", ASSET_STATUS_UNPROCESSED),
                strategy=strategies.get(relpath, AssetStrategy.SIMPLE.value),
                dirty=relpath in dirty_set,
                technical_score=status_entry.get("technical_score"),
                reason=status_entry.get("reason"),
                error=status_entry.get("error"),
                # 縮圖快取鍵用 relpath(避免 raw / standardized 同名 basename 互相覆蓋)
                thumbnail_url=self._thumbnails.ensure_url(
                    user_id, project, relpath, file_path, media_kind
                ),
                size_bytes=stat.st_size,
                modified_at=_iso_from_mtime(stat.st_mtime),
            ))
        return views

    def get_asset_detail(self, user_id: str, project: str, path: str) -> AssetDetailView:
        """
        取得單一素材的完整詳情:重用 ``list_assets`` 的 join 取得 ``AssetView``,再補上 /static
        原始媒體 URL(未裁切全圖 / 完整影片)與 Phase 1 完整感知 metadata。

        ``path`` 為素材身分 relpath。重用 list_assets 而非另寫一份讀取,使狀態 / 策略 / dirty /
        縮圖的 join 規則維持單一來源(DRY);素材量級小,多掃一次目錄成本可忽略。查無該素材拋
        FileNotFoundError(端點轉 404)。
        """
        project_dir = self._project_dir(user_id, project)
        # 沿用既有 join 取單檔檢視(與 set_strategy 結尾同手法);查無視為素材不存在
        view = next(
            (v for v in self.list_assets(user_id, project) if v.path == path),
            None,
        )
        if view is None:
            raise FileNotFoundError(f"找不到素材: {path}")

        # 只有 success 素材有完整 metadata;rejected / error / unprocessed 回 None,前端走狀態說明分支
        record = self._read_metadata_map(project_dir).get(path)
        metadata = record.get("metadata") if record else None
        metadata_kind = record.get("type") if record else None

        return AssetDetailView(
            asset=view,
            media_url=self._build_media_url(user_id, project, path),
            media_mime=_EXT_TO_MIME.get(os.path.splitext(path)[1].lower()),
            metadata=metadata,
            metadata_kind=metadata_kind,
        )

    def _build_media_url(self, user_id: str, project: str, path: str) -> str:
        """
        組單一素材的 /static 原始媒體完整 URL。

        ``path`` 為含子目錄的 relpath,以 ``quote(safe='/')`` 保留分隔斜線(僅編碼中文 / 空白等),
        組成 ``/static/{user}/{project}/{relpath}``,直接命中 StaticFiles 掛載的磁碟分層。
        """
        return f"{self._backend_url}/static/{user_id}/{project}/{quote(path, safe='/')}"

    def set_strategy(self, user_id: str, project: str, path: str, strategy: str) -> AssetView:
        """
        設定單一素材(以 relpath ``path`` 識別)的策略並依「是否偏離上次分析所用策略」更新 dirty。

        以 analyzed_strategies 為基準:策略改回上次分析值→清除 dirty;偏離→標記待重跑。
        經 ``project_meta_store.update`` 在 per-path 鎖內讀-改-寫,確保批量併發改策略不互相覆蓋
        (杜絕 lost update),亦保留 meta 其餘欄位。回傳更新後的檢視。
        """
        if strategy not in (AssetStrategy.SIMPLE.value, AssetStrategy.COMPLEX.value):
            raise ValueError(f"不支援的策略: {strategy}")
        project_dir = self._project_dir(user_id, project)
        if not self._asset_exists(project_dir, path):
            raise FileNotFoundError(f"找不到素材: {path}")

        def _mutate(meta: dict) -> None:
            """就地更新該檔策略,並依「是否偏離上次分析基準」加 / 清 dirty。"""
            meta.setdefault(META_KEY_ASSET_STRATEGIES, {})[path] = strategy
            # 基準為上次分析所用策略(未分析過視為 SIMPLE):回到基準即毋須重跑,偏離才標記待重跑
            baseline = meta.get(META_KEY_ANALYZED_STRATEGIES, {}).get(
                path, AssetStrategy.SIMPLE.value
            )
            dirty = set(meta.get(META_KEY_DIRTY_ASSETS, []))
            if strategy == baseline:
                dirty.discard(path)
            else:
                dirty.add(path)
            meta[META_KEY_DIRTY_ASSETS] = sorted(dirty)

        project_meta_store.update(project_dir, _mutate)

        # 回傳該檔最新檢視(策略已更新、dirty 已依基準調整)
        return next(v for v in self.list_assets(user_id, project) if v.path == path)

    def select_pending(self, user_id: str, project: str) -> list[str]:
        """回傳「dirty(策略變更)∪ 未處理」的素材 relpath 清單,供「開始生成」只重跑需要的素材。"""
        project_dir = self._project_dir(user_id, project)
        meta = self._read_meta(project_dir)
        dirty = set(meta.get(META_KEY_DIRTY_ASSETS, []))
        status_map = self._read_status_map(project_dir)
        pending: list[str] = []
        for relpath in collect_asset_files(project_dir):
            if relpath in dirty or relpath not in status_map:
                pending.append(relpath)
        return pending

    def get_asset_strategies(self, user_id: str, project: str) -> dict[str, str]:
        """取得逐檔策略表(供 run_phase1 套用);無設定回空 dict。"""
        project_dir = self._project_dir(user_id, project)
        return self._read_meta(project_dir).get(META_KEY_ASSET_STRATEGIES, {})

    def clear_dirty(self, user_id: str, project: str, filenames: Optional[list[str]] = None) -> None:
        """
        Phase 1 成功後清除 dirty 標記,並把這些素材的「已分析策略」基準推進到當前策略。

        基準(analyzed_strategies)供 set_strategy 判斷回退:把策略改回上次分析所用值即不再 dirty。
        ``filenames``(實為 relpath 清單)為 None 代表整個專案全部重分析(清空 dirty 並更新所有素材
        基準);否則只處理指定 relpath。經 ``project_meta_store.update`` 在鎖內讀-改-寫,避免與併發的
        改策略互相覆蓋。
        """
        project_dir = self._project_dir(user_id, project)
        # None 代表全部素材:磁碟掃描放在交易外(不需持鎖,亦避免拉長臨界區)
        if filenames is None:
            analyzed_targets = collect_asset_files(project_dir)
        else:
            analyzed_targets = filenames

        def _mutate(meta: dict) -> None:
            """就地推進已分析基準,並清掉本次完成者的 dirty(None 代表清空整份 dirty)。"""
            strategies = meta.get(META_KEY_ASSET_STRATEGIES, {})
            analyzed = dict(meta.get(META_KEY_ANALYZED_STRATEGIES, {}))
            dirty = set(meta.get(META_KEY_DIRTY_ASSETS, []))
            remaining = set() if filenames is None else dirty - set(filenames)
            # 推進基準至當前策略(未設定者視為 SIMPLE),供下次 set_strategy 的回退判斷
            for fname in analyzed_targets:
                analyzed[fname] = strategies.get(fname, AssetStrategy.SIMPLE.value)
            meta[META_KEY_ANALYZED_STRATEGIES] = analyzed
            meta[META_KEY_DIRTY_ASSETS] = sorted(remaining)

        project_meta_store.update(project_dir, _mutate)

    @staticmethod
    def _asset_exists(project_dir: str, path: str) -> bool:
        """確認某 relpath 確實是該專案的素材(經同一套探索規則,擋掉路徑穿越與非素材檔)。"""
        return path in set(collect_asset_files(project_dir))


def _iso_from_mtime(mtime: float) -> str:
    """把檔案 mtime(unix 秒)轉成 UTC ISO8601 字串(與專案其餘時間格式一致)。"""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
