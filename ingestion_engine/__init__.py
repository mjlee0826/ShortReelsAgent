"""
Layer 0 雲端攝取模組 (Ingestion Engine)。

把「公開資料夾 URL → 一個 project → 增量下載 → 觸發 Phase 1」整條攝取流程封裝在此套件，
與 backend 解耦（透過注入的 phase1_runner callback 觸發 Phase 1）。雲端來源與同步狀態折進各
project 的 project_meta.json，不另建註冊檔。公開類別於此集中匯出，供 ingestion_provider 接線使用。
"""
from ingestion_engine.cloud_ingestion_service import CloudIngestionService
from ingestion_engine.cloud_storage_adapter import CloudStorageAdapter
from ingestion_engine.exceptions import (
    IngestionError,
    RemoteAccessError,
    RemoteAuthError,
)
from ingestion_engine.models import (
    RemoteEntry,
    SyncReport,
)
from ingestion_engine.poller import IngestionPoller
from ingestion_engine.public_drive_api_adapter import PublicDriveApiAdapter

__all__ = [
    "CloudIngestionService",
    "CloudStorageAdapter",
    "PublicDriveApiAdapter",
    "IngestionError",
    "RemoteAccessError",
    "RemoteAuthError",
    "RemoteEntry",
    "SyncReport",
    "IngestionPoller",
]
