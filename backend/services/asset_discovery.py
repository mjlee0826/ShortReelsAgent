"""
素材檔案探索 (Pure Function / DRY)。

Phase 1 感知分析與前端 Asset Management 列表都需要「一個專案資料夾內哪些檔案算素材」的
同一套規則。把它集中於此單一函式,避免 director_service 與 asset_repository 各寫一份而走偏:
- 原始檔若已有對應 ``_std`` 標準化版本,只保留標準化版(避免同一素材重複)。
- 僅保留圖片 / 影片副檔名白名單(以 ``context`` 的 IMAGE/VIDEO 副檔名為單一來源)。
"""
from __future__ import annotations

import os

from media_processor.pipeline.context import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

# Phase 1 感知分析支援的媒體副檔名(圖片 ∪ 影片;不含純音訊,音訊由 Phase 3 處理)
SUPPORTED_MEDIA_EXTENSIONS: frozenset[str] = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# Phase 1 全狀態落地檔(含 success / rejected / error,鍵為檔名),供前端素材列表 join 狀態。
# 與 success-only 的 phase1_assets_metadata.json(Phase 4 用)區分。
PHASE1_STATUS_FILENAME = "phase1_asset_status.json"

# 標準化輸出檔名的標記片段(原始檔若已有此版本則被略過)
_STANDARDIZED_MARKER = "_std"


def collect_asset_files(target_dir: str) -> list[str]:
    """
    列出資料夾內待處理的素材檔絕對路徑,回傳順序即 ``os.listdir`` 順序(保證輸出排序穩定)。

    與舊 ``DirectorService._collect_asset_files`` 規則逐字一致:跳過已有 ``_std`` 版本的原始檔、
    僅收副檔名白名單內的檔案。
    """
    all_files = [
        f for f in os.listdir(target_dir)
        if os.path.isfile(os.path.join(target_dir, f))
    ]
    asset_files: list[str] = []
    for filename in all_files:
        # 原始檔若已有對應 _std 版本,跳過原始檔(只處理標準化後的版本)
        if f"{_STANDARDIZED_MARKER}." not in filename:
            std_version = os.path.splitext(filename)[0] + _STANDARDIZED_MARKER
            if any(std_version in f for f in all_files):
                continue
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_MEDIA_EXTENSIONS:
            continue
        asset_files.append(os.path.join(target_dir, filename))
    return asset_files
