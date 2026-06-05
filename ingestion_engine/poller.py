"""
背景輪詢器 (Background Task)。

後端啟動時拉起一個 asyncio 背景迴圈，定期掃描所有 user 的 project_meta.json，挑出雲端來源
(source=gdrive) 且「已達輪詢間隔」者並行觸發同步。阻塞的 Drive API／Phase 1 一律丟到 thread
(`asyncio.to_thread`)，不卡 event loop；per-project 進行中旗標避免自我重疊。

不再依賴獨立註冊檔：雲端來源與同步狀態折進各 project 的 project_meta.json，本輪詢器直接掃檔。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config.app_config import ASSETS_DIR
from config.ingestion_config import INGESTION_POLL_INTERVAL_SEC, POLLER_TICK_SEC
from ingestion_engine.cloud_ingestion_service import CloudIngestionService
from ingestion_engine.models import (
    META_KEY_LAST_SYNCED_AT,
    META_KEY_SOURCE,
    META_KEY_SYNC_STATUS,
    SOURCE_GDRIVE,
    SYNC_STATUS_PAUSED_AUTH,
)

_META_FILENAME = "project_meta.json"


@dataclass(frozen=True)
class _DueProject:
    """待同步的 project 定位（user 與 project 名）；frozen 以便放入 in-flight 集合。"""

    user_id: str
    project_name: str


class IngestionPoller:
    """定期挑出到期雲端 project 並背景同步的輪詢器。"""

    def __init__(
        self,
        service: CloudIngestionService,
        base_dir: str = ASSETS_DIR,
        tick_sec: int = POLLER_TICK_SEC,
    ):
        """注入同步協調層；base_dir 為素材根目錄；tick_sec 為迴圈醒來週期。"""
        self._service = service
        self._base_dir = base_dir
        self._tick_sec = tick_sec
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        # 正在同步中的 project；避免上一輪未跑完又被下一輪重複觸發
        self._in_flight: set[_DueProject] = set()

    # ── 生命週期 ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """啟動背景輪詢迴圈（冪等：已在跑則略過）。"""
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run_loop())
        print(f"[IngestionPoller] 已啟動，tick={self._tick_sec}s")

    async def stop(self) -> None:
        """請求停止並等待迴圈優雅收尾。"""
        if self._task is None:
            return
        self._stopped.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        print("[IngestionPoller] 已停止")

    # ── 迴圈內部 ──────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """主迴圈：每 tick 跑一輪同步，例外永不讓迴圈死掉；收到停止訊號即退出。"""
        while not self._stopped.is_set():
            try:
                await self._tick_once()
            except Exception as exc:  # best-effort：單輪失敗不應終結整個輪詢
                print(f"⚠️ [IngestionPoller] 本輪同步發生未預期錯誤: {exc}")
            # 以可中斷的等待取代 sleep：stop() 時能立刻醒來退出
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._tick_sec)
            except asyncio.TimeoutError:
                pass  # 正常 tick，繼續下一輪

    async def _tick_once(self) -> None:
        """挑出到期 project，並行各自背景同步。"""
        due = self._collect_due()
        if not due:
            return
        await asyncio.gather(
            *(self._sync_one(target) for target in due),
            return_exceptions=True,
        )

    def _collect_due(self) -> list[_DueProject]:
        """掃描全系統 project_meta，回傳到期且未在同步中的雲端 project（授權暫停者跳過）。"""
        now = time.time()
        due: list[_DueProject] = []
        for user_id in self._list_subdirs(self._base_dir):
            user_dir = os.path.join(self._base_dir, user_id)
            for project_name in self._list_subdirs(user_dir):
                meta = self._read_meta(os.path.join(user_dir, project_name))
                if meta is None or meta.get(META_KEY_SOURCE) != SOURCE_GDRIVE:
                    continue
                # 授權暫停者不自動重試（需重新分享後由手動 sync 喚醒）
                if meta.get(META_KEY_SYNC_STATUS) == SYNC_STATUS_PAUSED_AUTH:
                    continue
                target = _DueProject(user_id=user_id, project_name=project_name)
                if target in self._in_flight:
                    continue
                if self._is_due(meta, now):
                    due.append(target)
        return due

    async def _sync_one(self, target: _DueProject) -> None:
        """把單一 project 的阻塞同步丟到 thread 執行，並維護進行中旗標。"""
        self._in_flight.add(target)
        try:
            await asyncio.to_thread(
                self._service.sync_project, target.user_id, target.project_name
            )
        except Exception as exc:  # 單一 project 失敗不影響其他
            print(f"⚠️ [IngestionPoller] project {target.project_name} 同步失敗: {exc}")
        finally:
            self._in_flight.discard(target)

    # ── 純函式工具 ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_due(meta: dict, now: float) -> bool:
        """判斷 project 是否已達輪詢間隔（從未同步過者一律到期）。"""
        last = meta.get(META_KEY_LAST_SYNCED_AT)
        if not last:
            return True
        try:
            last_ts = datetime.fromisoformat(last).timestamp()
        except ValueError:
            return True  # 壞時間戳視為到期，下一輪會覆寫成合法值
        return (now - last_ts) >= INGESTION_POLL_INTERVAL_SEC

    @staticmethod
    def _list_subdirs(path: str) -> list[str]:
        """列出某路徑下的子資料夾名稱；路徑不存在或無法讀取回空清單。"""
        try:
            return [
                name for name in os.listdir(path)
                if os.path.isdir(os.path.join(path, name))
            ]
        except OSError:
            return []

    @staticmethod
    def _read_meta(project_dir: str) -> Optional[dict]:
        """讀取 project_meta.json；不存在或損毀回 None。"""
        meta_path = os.path.join(project_dir, _META_FILENAME)
        if not os.path.exists(meta_path):
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
