"""
素材檔案探索 (Pure Function / DRY)。

Phase 1 感知分析與前端 Asset Management 列表都需要「一個專案資料夾內哪些檔案算素材」的
同一套規則。把它集中於此單一函式,避免 director_service 與 asset_repository 各寫一份而走偏:
- 原始檔若已有對應 ``_std`` 標準化版本,只保留標準化版(避免同一素材重複)。
- 僅保留圖片 / 影片副檔名白名單(以 ``context`` 的 IMAGE/VIDEO 副檔名為單一來源)。

**素材身分 = 相對 project root 的 relpath**(B 方案):磁碟分層成 ``raw/``(原始)與
``standardized/``(``_std`` 衍生),``collect_asset_files`` 掃這兩層並回傳如 ``raw/photo.jpg``、
``standardized/clip_std.mp4`` 的 relpath。此 relpath 一路作為 status / metadata / 策略 meta 的鍵、
blueprint 的 ``clip_id``、以及 ``/static`` URL 片段,讓 ``root + relpath`` 直接命中磁碟。
"""
from __future__ import annotations

import os

from config.app_config import RAW_SUBDIR, STANDARDIZED_MARKER, STANDARDIZED_SUBDIR
from config.media_formats import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from config.project_artifacts import PHASE1_METADATA_FILENAME, PHASE1_STATUS_FILENAME

# Phase 1 感知分析支援的媒體副檔名(圖片 ∪ 影片;不含純音訊,音訊由 Phase 3 處理)
SUPPORTED_MEDIA_EXTENSIONS: frozenset[str] = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# PHASE1_STATUS_FILENAME / PHASE1_METADATA_FILENAME 改由 config.project_artifacts 提供(見頂部 import),
# 於此 re-export 維持既有 `from asset_discovery import PHASE1_*` 的下游相容(asset_repository / cover / director)。
# 標準化標記亦改用 config.app_config.STANDARDIZED_MARKER(原始檔已有此版本則被略過)。


def to_abs_path(project_dir: str, relpath: str) -> str:
    """
    把素材 relpath(如 ``raw/photo.jpg``)還原成本機絕對路徑。

    relpath 一律以正斜線表達(身分需與 URL / JSON 鍵一致),故以 ``split('/')`` 拆段再 join,
    確保在任何作業系統的路徑分隔符下都正確還原。
    """
    return os.path.join(project_dir, *relpath.split("/"))


def _list_media_in_subdir(project_dir: str, subdir: str) -> list[str]:
    """列出某子目錄(raw / standardized)內的檔名,依名稱排序確保輸出穩定;子目錄不存在回空 list。"""
    sub_path = os.path.join(project_dir, subdir)
    if not os.path.isdir(sub_path):
        return []
    return sorted(
        f for f in os.listdir(sub_path)
        if os.path.isfile(os.path.join(sub_path, f))
    )


def collect_asset_files(target_dir: str) -> list[str]:
    """
    列出專案內待處理的素材**relpath**(如 ``raw/photo.jpg``、``standardized/clip_std.mp4``)。

    規則(沿用舊邏輯但跨 ``raw/`` 與 ``standardized/`` 兩層):
    - 掃 ``raw/`` 的原始檔與 ``standardized/`` 的 ``_std`` 衍生檔。
    - 原始檔若在 ``standardized/`` 已有對應 ``_std`` 版本,只保留標準化版(避免同一素材重複計數)。
    - 僅收圖片 / 影片副檔名白名單內的檔案(純音訊不算視覺素材,由 Phase 3 處理)。

    回傳依「raw 在前、standardized 在後,各自名稱排序」的穩定順序。
    """
    raw_files = _list_media_in_subdir(target_dir, RAW_SUBDIR)
    std_files = _list_media_in_subdir(target_dir, STANDARDIZED_SUBDIR)

    asset_relpaths: list[str] = []
    # raw 原始檔:已有對應 standardized/_std 版本者跳過(只保留標準化版)
    for filename in raw_files:
        if _is_supported(filename) and not _has_standardized_version(filename, std_files):
            asset_relpaths.append(f"{RAW_SUBDIR}/{filename}")
    # standardized 衍生檔:皆為標準化後的有效素材
    for filename in std_files:
        if _is_supported(filename):
            asset_relpaths.append(f"{STANDARDIZED_SUBDIR}/{filename}")
    return asset_relpaths


def _is_supported(filename: str) -> bool:
    """判斷檔名副檔名是否在圖片 / 影片白名單內。"""
    return os.path.splitext(filename)[1].lower() in SUPPORTED_MEDIA_EXTENSIONS


def _has_standardized_version(raw_filename: str, std_files: list[str]) -> bool:
    """判斷某 raw 原始檔是否已有對應 ``_std`` 標準化版本(沿用舊的 ``{stem}_std`` 子字串比對)。"""
    std_version = os.path.splitext(raw_filename)[0] + STANDARDIZED_MARKER
    return any(std_version in f for f in std_files)
