"""
專案中繼資料儲存庫 (Repository Pattern)。

集中 ``project_meta.json`` 的「原子寫入 + 容錯讀取 + 交易式更新」。原本 projects / asset_repository /
director_service 各自有一份直接 ``open('w')`` 的非原子寫入;在 NFS 上「截斷 + 寫入」並非原子
操作,當多個來源(REST 請求的回填寫、生成 job 的 meta 更新、背景同步 poller)併發寫同一檔時,
會留下「一段合法 JSON 後接前一版殘留位元組」的 *Extra data* 損毀,進而讓整個 /api/projects
直接 500。

設計重點:
- **寫入原子化**:一律寫到同目錄的**唯一** temp 檔再 ``os.replace`` 置換,讀者永遠看到完整檔。
  temp 檔以 ``mkstemp`` 取唯一名而非固定 ``.tmp``:固定名會被另一併發寫者 ``open('w')`` 截斷 /
  交錯而換入損毀內容(批量改策略時多個 PATCH 併發即觸發)。
- **讀取容錯**:正常 parse 失敗時,以 ``raw_decode`` 取回檔案開頭的合法 JSON 段落
  (即 Extra data 型損毀的真正內容)並順手原子修復檔案;真的取不回才視為缺檔回 ``None``,
  避免一個壞檔讓整份專案列表崩潰,也避免把雲端來源等欄位整份清掉。
- **交易式更新**:``update`` 以 per-path 鎖序列化同一檔的「讀-改-寫」,杜絕併發 lost update
  (批量改策略時部分變更被覆蓋)。鎖為同進程內的 ``threading.Lock``。

meta 刻意以開放式 ``dict`` 表示而非 pydantic 模型:不同寫入者各自附加欄位(本地 / 雲端來源 /
逐檔策略),讀-改-寫須原樣保留未知欄位;型別化的視圖由 API 邊界的 ``ProjectMeta`` 負責。

注意:``ingestion_engine`` 受「不得 import backend」的反循環依賴約束,沿用其自身等價的原子實作,
不共用本模組(其 temp 唯一化亦已同步處理,杜絕跨元件的 temp 互踩損毀)。
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from typing import Callable, Optional

# 專案中繼資料檔名(單一事實來源)
PROJECT_META_FILENAME = "project_meta.json"

# 原子寫入的暫存檔副檔名
_TMP_SUFFIX = ".tmp"


class ProjectMetaStore:
    """``project_meta.json`` 的原子寫入 / 容錯讀取 / 交易式更新儲存庫。"""

    def __init__(self) -> None:
        """初始化 per-path 鎖登錄表(序列化同一檔的併發讀-改-寫,杜絕 lost update)。"""
        # 每個 meta 路徑一把鎖:批量改策略等併發更新據此序列化
        self._locks: dict[str, threading.Lock] = {}
        # 保護 _locks 自身的延遲建立(臨界區極短)
        self._locks_guard = threading.Lock()

    def read(self, project_dir: str) -> Optional[dict]:
        """
        讀取專案 meta;檔案缺失或完全無法復原時回 ``None``。

        遇到 JSON 損毀先嘗試復原開頭合法段落(對應 NFS 併發非原子寫造成的「Extra data」),
        以免尾端殘留位元組導致整份 meta 丟失。
        """
        return self._read_path(os.path.join(project_dir, PROJECT_META_FILENAME))

    def write(self, project_dir: str, meta: dict) -> None:
        """以唯一 temp 檔 + ``os.replace`` 原子寫回 meta,杜絕併發讀者讀到半寫內容。"""
        self._atomic_dump(os.path.join(project_dir, PROJECT_META_FILENAME), meta)

    def update(self, project_dir: str, mutator: Callable[[dict], None]) -> dict:
        """
        於 per-path 鎖內原子地對 meta 做「讀-改-寫」交易,回傳更新後的 meta。

        ``mutator`` 就地修改傳入的 dict;同一專案的併發更新(如批量改策略的多個 PATCH)會被
        序列化,確保每筆變更都不遺失(杜絕 lost update),且每次落地都是完整檔。
        """
        meta_path = os.path.join(project_dir, PROJECT_META_FILENAME)
        with self._lock_for(meta_path):
            meta = self._read_path(meta_path) or {}
            mutator(meta)  # 呼叫端就地修改;鎖確保整段交易不被併發打斷
            self._atomic_dump(meta_path, meta)
        return meta

    # ── 內部工具 ──────────────────────────────────────────────────────────────

    def _lock_for(self, meta_path: str) -> threading.Lock:
        """取得某 meta 路徑專屬的鎖(不存在則延遲建立);序列化該檔的併發更新。"""
        with self._locks_guard:
            lock = self._locks.get(meta_path)
            if lock is None:
                lock = threading.Lock()
                self._locks[meta_path] = lock
            return lock

    def _read_path(self, meta_path: str) -> Optional[dict]:
        """以絕對路徑讀 meta;缺檔 / 無法讀取回 ``None``,JSON 損毀則嘗試復原開頭合法段落。"""
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return None  # 不存在 / 無法讀取
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return self._recover(meta_path, raw)

    def _recover(self, meta_path: str, raw: str) -> Optional[dict]:
        """從損毀內容取回開頭合法 JSON 段落;成功則原子修復檔案,否則回 ``None``。"""
        try:
            # raw_decode 只解析開頭一個 JSON 值、忽略其後殘留位元組(正是 Extra data 損毀的型態)
            meta, _ = json.JSONDecoder().raw_decode(raw.lstrip())
        except json.JSONDecodeError:
            print(f"[ProjectMetaStore Error] meta 損毀且無法復原,視為缺檔: {meta_path}")
            return None
        print(f"[ProjectMetaStore Warning] meta 損毀,已從開頭合法段落復原並修復: {meta_path}")
        try:
            self._atomic_dump(meta_path, meta)  # 把乾淨內容寫回,後續讀取不再走復原路徑
        except OSError:
            pass  # 修復寫入失敗無妨,下次讀取仍可即時復原
        return meta

    @staticmethod
    def _atomic_dump(meta_path: str, meta: dict) -> None:
        """
        寫入**唯一** temp 檔再 ``os.replace`` 原子置換(同檔系上的置換具原子性)。

        temp 以 ``mkstemp`` 取唯一名:固定共用 ``.tmp`` 會被另一併發寫者 ``open('w')`` 截斷 /
        交錯,導致換入「Extra data」損毀內容;唯一 temp 讓併發寫者互不干擾。
        """
        dir_name = os.path.dirname(meta_path) or "."
        # 同目錄建唯一 temp,確保與目標同檔系(os.replace 才具原子性)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_name, prefix=f"{PROJECT_META_FILENAME}.", suffix=_TMP_SUFFIX
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, meta_path)
        except BaseException:
            # 寫入 / 置換失敗:清掉殘留 temp,避免目錄堆積半寫檔,再把原例外拋回
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise


# 模組級單例(與 apiService / cloud_ingestion_service 一致的使用慣例)
project_meta_store = ProjectMetaStore()
