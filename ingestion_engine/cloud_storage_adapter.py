"""
雲端儲存存取介面 (Adapter Pattern)。

`CloudStorageAdapter` 定義「解析來源 URL／列檔／下載資料夾」三個攝取所需的最小介面。
位址以 adapter 不透明的 **locator** 字串表達（Drive 實作即資料夾／檔案 ID），上層
同步協調層完全不知道底層是哪種雲端，未來新增其他雲端只需再實作一個 adapter，主邏輯不動。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ingestion_engine.models import RemoteEntry


class CloudStorageAdapter(ABC):
    """雲端儲存存取介面：解析來源 URL 成 locator、列媒體檔、下載資料夾到本地。"""

    @abstractmethod
    def parse_source(self, source_url: str) -> str:
        """把使用者提供的來源（資料夾 URL）解析為根 locator；無法解析時 raise ValueError。"""
        raise NotImplementedError

    @abstractmethod
    def list_files(self, folder_locator: str) -> list[RemoteEntry]:
        """列出 folder_locator 底下「一層」的媒體檔（不含子資料夾，已套副檔名白名單）。"""
        raise NotImplementedError

    @abstractmethod
    def download_folder(self, folder_locator: str, dest_dir: str) -> None:
        """把 folder_locator 內的媒體檔增量下載到本地 dest_dir（已存在且同大小者跳過）。"""
        raise NotImplementedError
