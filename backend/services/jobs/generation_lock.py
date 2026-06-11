"""
blueprint 生成(Phase 2–4)執行互斥鎖 (per-(user, project) Facade)。

比照 ``phase1_lock``:重用其 ``KeyedLockRegistry``,對同一專案的生成併發互斥。編輯頁中途離開
重進再按生成時,偵測鎖已持有 → 端點回既有 job 讓前端附掛,而非 double-run(否則兩生成併寫
``PHASE4_BLUEPRINT_FILENAME`` last-writer-wins + 雙倍 GPU,見 docs/blueprint_prep_design.md §10.9)。
鎖在 ``work`` 的 ``finally`` 釋放。

``threading.Lock.release()`` 允許由「非取得者執行緒」呼叫(同 ``phase1_lock`` 模組 docstring),
故可在 async 端點(event loop 執行緒)取鎖、於背景 worker thread 的 ``finally`` 釋放(以 Lock 當 gate)。
與 ``phase1_lock`` 刻意分開:兩者涵蓋的工作不同(Phase 1 感知 vs Phase 2–4 生成),互不阻擋。
"""
from __future__ import annotations

from typing import Optional

from backend.services.jobs.phase1_lock import KeyedLockRegistry

# threading.Lock.acquire 的 timeout 慣例:-1 表示無限等(僅 blocking=True 時有效)
_NO_TIMEOUT = -1.0


class GenerationLock:
    """
    per-(user, project) 的生成執行鎖 Facade(較 ``Phase1Lock`` 精簡:無 activity 標籤需求)。

    以 ``user_id`` 與專案名組成鍵(確保鎖鍵一致、零路徑漂移),對外只暴露 acquire / release,
    內部委派 ``KeyedLockRegistry``。
    """

    def __init__(self) -> None:
        """初始化底層鍵控鎖登錄表。"""
        self._registry = KeyedLockRegistry()

    @staticmethod
    def _key(user_id: Optional[str], project: str) -> str:
        """組鎖鍵;user_id 可能為 None(CLI / 無認證),以固定前綴避免與真實 user 撞鍵。"""
        return f"{user_id or '_anon'}/{project}"

    def acquire(self, user_id: Optional[str], project: str, *,
                blocking: bool = False, timeout: float = _NO_TIMEOUT) -> bool:
        """嘗試取得某專案的生成鎖;非阻塞(預設)搶不到即回 ``False``(端點據此回既有 job)。"""
        return self._registry.lock_for(self._key(user_id, project)).acquire(
            blocking=blocking, timeout=timeout
        )

    def release(self, user_id: Optional[str], project: str) -> None:
        """釋放某專案的生成鎖(允許由非取得者執行緒呼叫,見模組 docstring)。"""
        self._registry.lock_for(self._key(user_id, project)).release()


# 模組級單例:跨 API 請求與背景 job 共享同一組 per-project 生成鎖
generation_lock = GenerationLock()
