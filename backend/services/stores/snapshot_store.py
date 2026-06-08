"""
編輯器具名快照儲存庫 (Repository Pattern)。

集中編輯器「版本檢查點」(snapshot) 的原子讀寫:每個專案資料夾一份
``editor_snapshots.json`` (list,每筆 ``{ id, label, created_at, blueprint }``)。
快照供編輯器左欄版本清單跨重整還原,與前端 undo 的線性堆疊互補。

設計重點:
- **寫入原子化 + 讀取容錯**:複用 ``atomic_write_json`` / ``read_json_tolerant``(NFS 上
  避免半寫損毀讓整頁 500)。
- **交易式更新**:``add`` / ``delete`` 以 per-path 鎖序列化同一檔的「讀-改-寫」,杜絕併發
  lost update。鎖為同進程內的 ``threading.Lock``(與 ``ProjectMetaStore`` 同慣例)。
- **list 與 get 分離**:列表只回 meta(不含 blueprint)以縮小 payload;還原時才以 id 取完整快照。
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from config.project_artifacts import EDITOR_SNAPSHOTS_FILENAME
from backend.utils.atomic_json import atomic_write_json, read_json_tolerant

# 每專案保留的快照上限:超過則丟最舊者,避免檔案無限成長(具名常數,禁 magic number)
MAX_SNAPSHOTS = 50


class SnapshotStore:
    """``editor_snapshots.json`` 的原子寫入 / 容錯讀取 / 交易式更新儲存庫。"""

    def __init__(self) -> None:
        """初始化 per-path 鎖登錄表(序列化同一檔的併發讀-改-寫)。"""
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def list_meta(self, project_dir: str) -> list[dict]:
        """回傳快照 meta 列表(不含 blueprint),依建立時間新→舊排序。"""
        snapshots = self._read(project_dir)
        metas = [self._to_meta(s) for s in snapshots]
        # 新的在前,符合版本清單由上而下「最新→最舊」的直覺
        metas.sort(key=lambda m: m["created_at"], reverse=True)
        return metas

    def add(self, project_dir: str, label: str, blueprint: dict) -> dict:
        """新增一筆快照(交易式),回傳新快照的 meta;超出上限則丟棄最舊者。"""
        snapshot = {
            "id": uuid.uuid4().hex,
            "label": label,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "blueprint": blueprint,
        }
        path = self._path(project_dir)
        with self._lock_for(path):
            snapshots = self._read(project_dir)
            snapshots.append(snapshot)
            # 依建立時間保留最新的 MAX_SNAPSHOTS 筆(丟最舊)
            snapshots.sort(key=lambda s: s.get("created_at", ""))
            if len(snapshots) > MAX_SNAPSHOTS:
                snapshots = snapshots[-MAX_SNAPSHOTS:]
            atomic_write_json(path, snapshots)
        return self._to_meta(snapshot)

    def get(self, project_dir: str, snapshot_id: str) -> Optional[dict]:
        """以 id 取完整快照(含 blueprint);不存在回 None。"""
        for s in self._read(project_dir):
            if s.get("id") == snapshot_id:
                return s
        return None

    def delete(self, project_dir: str, snapshot_id: str) -> bool:
        """刪除指定 id 的快照(交易式);有刪到回 True,找不到回 False。"""
        path = self._path(project_dir)
        with self._lock_for(path):
            snapshots = self._read(project_dir)
            remaining = [s for s in snapshots if s.get("id") != snapshot_id]
            if len(remaining) == len(snapshots):
                return False
            atomic_write_json(path, remaining)
        return True

    # ── 內部工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _path(project_dir: str) -> str:
        """組出快照檔的絕對路徑。"""
        return os.path.join(project_dir, EDITOR_SNAPSHOTS_FILENAME)

    def _read(self, project_dir: str) -> list[dict]:
        """容錯讀取快照列表;缺檔 / 損毀回空 list。"""
        data = read_json_tolerant(self._path(project_dir), [])
        return data if isinstance(data, list) else []

    @staticmethod
    def _to_meta(snapshot: dict) -> dict:
        """把完整快照轉成 meta(不含 blueprint),供列表顯示。"""
        return {
            "id": snapshot.get("id"),
            "label": snapshot.get("label"),
            "created_at": snapshot.get("created_at"),
        }

    def _lock_for(self, path: str) -> threading.Lock:
        """取得某快照檔專屬的鎖(不存在則延遲建立)。"""
        with self._locks_guard:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock


# 模組級單例(與 project_meta_store 一致的使用慣例)
snapshot_store = SnapshotStore()
