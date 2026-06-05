"""
專案中繼資料儲存庫 (Repository Pattern)。

集中 ``project_meta.json`` 的「原子寫入 + 容錯讀取」。原本 projects / asset_repository /
director_service 各自有一份直接 ``open('w')`` 的非原子寫入;在 NFS 上「截斷 + 寫入」並非原子
操作,當多個來源(REST 請求的回填寫、生成 job 的 meta 更新、背景同步 poller)併發寫同一檔時,
會留下「一段合法 JSON 後接前一版殘留位元組」的 *Extra data* 損毀,進而讓整個 /api/projects
直接 500。

設計重點:
- **寫入原子化**:一律寫到同目錄 temp 檔再 ``os.replace`` 置換,讀者永遠看到完整檔
  (與 ingestion_engine 既有策略一致)。
- **讀取容錯**:正常 parse 失敗時,以 ``raw_decode`` 取回檔案開頭的合法 JSON 段落
  (即 Extra data 型損毀的真正內容)並順手原子修復檔案;真的取不回才視為缺檔回 ``None``,
  避免一個壞檔讓整份專案列表崩潰,也避免把雲端來源等欄位整份清掉。

meta 刻意以開放式 ``dict`` 表示而非 pydantic 模型:不同寫入者各自附加欄位(本地 / 雲端來源 /
逐檔策略),讀-改-寫須原樣保留未知欄位;型別化的視圖由 API 邊界的 ``ProjectMeta`` 負責。

注意:``ingestion_engine`` 受「不得 import backend」的反循環依賴約束,沿用其自身等價的原子實作,
不共用本模組。
"""
from __future__ import annotations

import json
import os
from typing import Optional

# 專案中繼資料檔名(單一事實來源)
PROJECT_META_FILENAME = "project_meta.json"

# 原子寫入的暫存檔副檔名
_TMP_SUFFIX = ".tmp"


class ProjectMetaStore:
    """``project_meta.json`` 的原子寫入 / 容錯讀取儲存庫。"""

    def read(self, project_dir: str) -> Optional[dict]:
        """
        讀取專案 meta;檔案缺失或完全無法復原時回 ``None``。

        遇到 JSON 損毀先嘗試復原開頭合法段落(對應 NFS 併發非原子寫造成的「Extra data」),
        以免尾端殘留位元組導致整份 meta 丟失。
        """
        meta_path = os.path.join(project_dir, PROJECT_META_FILENAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            return None  # 不存在 / 無法讀取
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return self._recover(meta_path, raw)

    def write(self, project_dir: str, meta: dict) -> None:
        """以 temp 檔 + ``os.replace`` 原子寫回 meta,杜絕併發讀者讀到半寫內容。"""
        self._atomic_dump(os.path.join(project_dir, PROJECT_META_FILENAME), meta)

    # ── 內部工具 ──────────────────────────────────────────────────────────────

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
        """寫入同目錄 temp 檔再 ``os.replace`` 原子置換(同檔系上的置換具原子性)。"""
        tmp_path = f"{meta_path}{_TMP_SUFFIX}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, meta_path)


# 模組級單例(與 apiService / cloud_ingestion_service 一致的使用慣例)
project_meta_store = ProjectMetaStore()
