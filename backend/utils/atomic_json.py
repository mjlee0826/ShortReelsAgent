"""
JSON 原子寫入與容錯讀取 (Pure Functions / DRY)。

``phase1_assets_metadata.json`` 與 ``phase1_status.json`` 原以 ``open('w')`` 直寫:在 NFS 上
「截斷 + 寫入」並非原子,併發寫會遺失更新,讀者(含素材頁 ``list_assets``)更可能讀到半截
JSON 而 500。集中於此提供:
- ``atomic_write_json``:寫唯一 temp 檔再 ``os.replace`` 原子置換,讀者恆見完整檔。
- ``read_json_tolerant``:解析失敗(半寫 / 損毀)回預設值而非拋例外,避免單一壞檔讓整頁崩潰。

與 ``ProjectMetaStore._atomic_dump`` 同構;後者另含 meta 專屬的 ``raw_decode`` 復原邏輯,
故二者各自保留(本模組供 phase1 dump 與其他一般 JSON 重用)。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from typing import Any
import logging

logger = logging.getLogger(__name__)

# 原子寫入的暫存檔副檔名(與目標同目錄、唯一命名,確保同檔系 os.replace 具原子性)
_TMP_SUFFIX = ".tmp"


def atomic_write_json(path: str, data: Any) -> None:
    """
    將 ``data`` 以 JSON 寫入 ``path``:先寫同目錄唯一 temp 檔,再 ``os.replace`` 原子置換。

    temp 以 ``mkstemp`` 取唯一名(非固定 ``.tmp``):固定名會被另一併發寫者 ``open('w')`` 截斷 /
    交錯而換入損毀內容。寫入 / 置換失敗則清掉殘留 temp 後把原例外拋回。
    """
    dir_name = os.path.dirname(path) or "."
    # 同目錄建唯一 temp(prefix 取目標 basename),確保與目標同檔系(os.replace 才具原子性)
    fd, tmp_path = tempfile.mkstemp(
        dir=dir_name, prefix=f"{os.path.basename(path)}.", suffix=_TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        # 寫入 / 置換失敗:清掉殘留 temp 避免目錄堆積半寫檔,再把原例外拋回
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def read_json_tolerant(path: str, default: Any) -> Any:
    """
    讀取並解析 JSON;檔案不存在 / 無法讀取 / 解析失敗時回傳 ``default``(不拋例外)。

    搭配 ``atomic_write_json`` 後半寫已不會發生;本函式作為「真損毀檔」的最後防線,避免單一
    壞檔讓素材頁等讀取端 500。解析失敗會 print 一行警告(沿用本專案 print log 慣例)。
    """
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[atomic_json Warning] 讀取 JSON 失敗,回傳預設值: {path} ({exc})")
        return default
