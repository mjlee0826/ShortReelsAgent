"""
偏好事件儲存庫 (Repository Pattern)。

集中「偏好資料飛輪」事件鏈的原子讀寫:每個專案資料夾一份 ``preference_events.json``
(append-only list,每筆 ``PreferenceEvent``)。每次導演生成(初始 / 對話微調)各落一筆
「AI 排 before → after,外加使用者指令」的事件,供離線(T1)還原成乾淨的偏好配對:

- 微調配對(指令↔修正):每筆 refinement 事件的 ``before + prompt → after``。
- 手動編輯配對(AI 排 X→人改 Y):相鄰事件 ``event[i].after → event[i+1].before``。

設計沿用 ``SnapshotStore`` / ``ProjectMetaStore`` 的同一組保證:**原子寫入 + 容錯讀取**
(複用 ``atomic_write_json`` / ``read_json_tolerant``,NFS 上避免半寫損毀)、**交易式更新**
(per-path ``threading.Lock`` 序列化同一檔的「讀-改-寫」,杜絕併發 lost update)。事件本身以
pydantic ``PreferenceEvent`` 型別化(符合專案資料結構規範)。
"""
from __future__ import annotations

import threading
import os
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from config.project_artifacts import PREFERENCE_EVENTS_FILENAME
from backend.utils.atomic_json import atomic_write_json, read_json_tolerant

# 事件結構版本:之後若調整欄位,靠此辨識舊資料(具名常數,禁 magic number)
PREFERENCE_EVENT_SCHEMA_VERSION = 1


class PreferenceEvent(BaseModel):
    """一次導演生成的偏好事件:AI 排 before→after,外加使用者指令與時間戳 (Value Object)。"""

    # 事件時間戳(ISO8601, UTC);預設工廠避免每筆都要呼叫端自填
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # 生成類型:初始生成 / 對話微調
    kind: Literal["initial", "refinement"]
    # 是否為微調(與 kind 同義,保留布林欄位便於離線過濾)
    is_refinement: bool
    # 使用者原始指令(微調指令或初始創作 brief;非 enhanced_prompt)
    prompt: str
    # 生成前的「人類側」藍圖:微調=前端送來的 old_timeline;初始=生成前舊 phase4(無則 None)
    before: Optional[dict] = None
    # 生成後實際落地的 final_blueprint(後處理完;與 autosave 對比 apples-to-apples)
    after: dict
    # 結構版本,供日後格式演進辨識
    schema_version: int = PREFERENCE_EVENT_SCHEMA_VERSION


class PreferenceEventStore:
    """``preference_events.json`` 的原子寫入 / 容錯讀取 / 交易式 append 儲存庫。"""

    def __init__(self) -> None:
        """初始化 per-path 鎖登錄表(序列化同一檔的併發讀-改-寫)。"""
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def append(self, project_dir: str, event: PreferenceEvent) -> None:
        """交易式新增一筆偏好事件到該專案的事件鏈尾端。

        不設保留上限:偏好事件即訓練資料,應全數保留;每專案生成 / 微調次數有限,
        無限成長風險低(與 SnapshotStore 的 50 筆上限刻意不同)。
        """
        path = self._path(project_dir)
        with self._lock_for(path):
            events = self._read(project_dir)
            events.append(event.model_dump())
            atomic_write_json(path, events)

    def read(self, project_dir: str) -> list[dict]:
        """容錯讀取某專案的偏好事件鏈;缺檔 / 損毀回空 list(供離線 T1 與測試取用)。"""
        return self._read(project_dir)

    # ── 內部工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _path(project_dir: str) -> str:
        """組出偏好事件檔的絕對路徑。"""
        return os.path.join(project_dir, PREFERENCE_EVENTS_FILENAME)

    def _read(self, project_dir: str) -> list[dict]:
        """容錯讀取事件 list;缺檔 / 損毀 / 型別不符回空 list。"""
        data = read_json_tolerant(self._path(project_dir), [])
        return data if isinstance(data, list) else []

    def _lock_for(self, path: str) -> threading.Lock:
        """取得某事件檔專屬的鎖(不存在則延遲建立)。"""
        with self._locks_guard:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock


# 模組級單例(與 snapshot_store / project_meta_store 一致的使用慣例)
preference_event_store = PreferenceEventStore()
