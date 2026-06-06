"""
專案封面挑選服務 (Service Pattern)。

為「專案總覽」每張卡片挑一張代表封面:讀該專案 success-only 的 Phase 1 感知結果
(phase1_assets_metadata.json),選出美學分數 (aesthetic_score) 最高的素材,委派 ThumbnailService
產生 / 取得其縮圖 URL。任何缺檔 / 壞檔 / 無可用素材都回 None(由前端改顯示中性佔位),
確保封面問題不影響專案列表本身。

美學分數僅圖片與一般影片有 (ComplexVideo 不打美學分),挑選時自動略過缺分者;
若全數缺分(例:整個專案都是 ComplexVideo),退而取第一筆成功素材,仍給一張真實縮圖。
"""
from __future__ import annotations

import json
import os
from typing import Optional

from backend.services.asset_discovery import PHASE1_METADATA_FILENAME, to_abs_path
from backend.services.thumbnail_service import ThumbnailService
from media_processor.pipeline.context import derive_media_kind

# phase1_assets_metadata.json 每筆條目的欄位鍵(具名常數,避免散落 magic string)
_ENTRY_KEY_FILE = "file"                      # 素材身分 relpath(如 raw/photo.jpg)
_ENTRY_KEY_METADATA = "metadata"             # 完整感知 metadata
_METADATA_KEY_AESTHETIC = "aesthetic_score"  # LAION 美學分(僅圖片 / 一般影片有)


class ProjectCoverService:
    """挑選專案封面素材並回傳其縮圖 URL;縮圖產生委派注入的 ThumbnailService。"""

    def __init__(self, thumbnail_service: Optional[ThumbnailService] = None):
        """注入縮圖服務(預設自建一個),比照 AssetRepository 的組裝方式。"""
        self._thumbnails = thumbnail_service or ThumbnailService()

    def resolve_cover_url(self, user_id: str, project: str, project_dir: str) -> Optional[str]:
        """
        回傳某專案封面(美學最高素材)的縮圖 URL;無可用素材或任何失敗都回 None。

        步驟:讀 success-only metadata → 選 aesthetic_score 最高(缺分者略過,全缺則取第一筆)
        → 由 relpath 身分還原本機素材路徑 → 委派 ThumbnailService 確保縮圖存在並組 URL。
        """
        try:
            entries = self._read_metadata(project_dir)
            best = self._pick_best_entry(entries)
            if best is None:
                return None
            relpath = best.get(_ENTRY_KEY_FILE, "")
            if not relpath:
                return None
            # file 為 relpath 身分(已含 raw/standardized 分層),直接還原本機絕對路徑(可跨機移植)
            src_path = to_abs_path(project_dir, relpath)
            if not os.path.isfile(src_path):
                return None
            media_kind = derive_media_kind(relpath)
            return self._thumbnails.ensure_url(user_id, project, relpath, src_path, media_kind)
        except Exception as exc:  # noqa: BLE001 - 封面非關鍵路徑,任何意外都退 None 改顯佔位
            print(f"[ProjectCoverService Warning] 解析封面失敗 ({project}): {exc}")
            return None

    @staticmethod
    def _read_metadata(project_dir: str) -> list[dict]:
        """讀 phase1_assets_metadata.json(success-only list);缺檔 / 結構非預期回空 list。"""
        path = os.path.join(project_dir, PHASE1_METADATA_FILENAME)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 防呆:檔案結構非預期(非 list)時視為無可用素材
        return data if isinstance(data, list) else []

    @staticmethod
    def _pick_best_entry(entries: list[dict]) -> Optional[dict]:
        """
        從 metadata 條目挑封面來源:優先取 aesthetic_score 最高者;
        全數缺美學分(例:整個專案皆 ComplexVideo)時退而取第一筆,確保仍有真實縮圖。
        """
        if not entries:
            return None
        # 僅保留「metadata 為 dict 且確有美學分」的條目參與比分,避免 None 進入 max 比較
        scored = [
            (entry[_ENTRY_KEY_METADATA][_METADATA_KEY_AESTHETIC], entry)
            for entry in entries
            if isinstance(entry.get(_ENTRY_KEY_METADATA), dict)
            and entry[_ENTRY_KEY_METADATA].get(_METADATA_KEY_AESTHETIC) is not None
        ]
        if scored:
            return max(scored, key=lambda pair: pair[0])[1]
        # 無任何美學分:退而取第一筆成功素材
        return entries[0]
