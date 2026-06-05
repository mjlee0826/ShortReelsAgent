"""
攝取層元件接線 (Composition Root / Dependency Injection)。

集中組裝 Layer 0 的單例：PublicDriveApiAdapter（Drive API 公開資料夾存取）、
CloudIngestionService（同步協調）、IngestionPoller（背景輪詢）。Phase 1 的觸發以 callback 注入，
callback 包一層既有的 director_service 單例（重用，不重複載入 facade），讓 ingestion_engine
與 backend 維持單向依賴、避免循環 import。

API 端點（backend/api/projects.py）與背景任務啟動（backend/main.py）皆從此處取用同一組單例。
"""
from __future__ import annotations

from backend.api.director import director_service
from ingestion_engine import (
    CloudIngestionService,
    IngestionPoller,
    PublicDriveApiAdapter,
)


def _phase1_runner(user_id: str, project_name: str) -> None:
    """攝取背景預跑的 Phase 1 觸發 callback：對指定本地 project 跑 Phase 1（預設 SIMPLE 策略）。"""
    director_service.run_phase1(project_name, user_id=user_id)


# 模組層級單例：跨 API 請求與背景輪詢共享同一份狀態與設定
drive_adapter = PublicDriveApiAdapter()
cloud_ingestion_service = CloudIngestionService(drive_adapter, _phase1_runner)
ingestion_poller = IngestionPoller(cloud_ingestion_service)
