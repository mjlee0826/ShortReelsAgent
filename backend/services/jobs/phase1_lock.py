"""
Phase 1 執行互斥鎖 (Keyed Lock Registry + Facade)。

``run_phase1``(標準化 + 感知 pipeline + 落地 metadata/status)有四個進入點:雲端同步背景
預跑、編輯頁完整生成、素材頁「重新分析」與「開始生成」。四者對同一專案併發跑會造成:
phase1 metadata/status 併發寫遺失更新、雙重佔用 GPU(共用機易 OOM)、dirty/已分析基準互踩。

本模組提供 per-(user, project) 的執行鎖,讓四條路徑對同一專案的 Phase 1 真正互斥:
- 素材頁兩顆按鈕:非阻塞 try,搶不到即由端點回 409(避免重複觸發堆積)。
- 編輯頁:阻塞等待(帶 timeout),等前景做完再讀新鮮快取。
- 雲端同步:非阻塞 try,搶不到即略過本輪(下輪 poller 重試)。

本鎖刻意與 ``CloudIngestionService`` 的同步鎖分開:同步鎖包含網路下載,本鎖只在實際 Phase 1
計算段被取,二者取得順序恆為「同步鎖 → 本鎖」且永不反向,無死鎖之虞。

``threading.Lock.release()`` 允許由「非取得者執行緒」呼叫(CPython 明文支援),故素材頁可在
async 端點(event loop 執行緒)取鎖、於背景 worker thread 的 ``finally`` 釋放(以 Lock 當 gate)。
"""
from __future__ import annotations

import threading
from typing import Optional

# 取鎖失敗 / 逾時時的使用者面向訊息(集中管理,禁 magic string 散落)
PHASE1_BUSY_MESSAGE = "素材分析中，請稍候"      # 素材頁兩顆按鈕:前景分析中,端點回 409
EDITOR_BUSY_MESSAGE = "分析進行中，請稍候再試"   # 編輯頁:等待前景逾時

# threading.Lock.acquire 的 timeout 慣例:-1 表示無限等(僅 blocking=True 時有效)
_NO_TIMEOUT = -1.0


class Phase1BusyError(Exception):
    """編輯頁等待前景 Phase 1 逾時:呼叫端據此回 409 / 帶回前端提示。"""


class KeyedLockRegistry:
    """
    依字串鍵延遲建立並快取 ``threading.Lock`` 的登錄表 (Registry Pattern)。

    與 ``ProjectMetaStore`` / ``CloudIngestionService`` 內各自的 per-path 鎖同構,抽成可重用元件:
    同一鍵恆回同一把鎖;``_guard`` 只保護「鎖字典自身」的延遲建立(臨界區極短)。
    """

    def __init__(self) -> None:
        """初始化鎖字典與保護其延遲建立的 guard。"""
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock_for(self, key: str) -> threading.Lock:
        """取得某鍵專屬的鎖(不存在則延遲建立)。"""
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock


class Phase1Lock:
    """
    per-(user, project) 的 Phase 1 執行鎖 Facade。

    以 ``user_id`` 與專案名組成鍵(四條進入點皆持有此二元組,確保鎖鍵一致、零路徑漂移),
    對外只暴露 acquire / release,內部委派 ``KeyedLockRegistry``。
    """

    def __init__(self) -> None:
        """初始化底層鍵控鎖登錄表。"""
        self._registry = KeyedLockRegistry()

    @staticmethod
    def _key(user_id: Optional[str], project: str) -> str:
        """組鎖鍵;user_id 可能為 None(CLI / 無認證),以固定前綴避免與真實 user 撞鍵。"""
        return f"{user_id or '_anon'}/{project}"

    def acquire(self, user_id: Optional[str], project: str, *,
                blocking: bool = True, timeout: float = _NO_TIMEOUT) -> bool:
        """
        嘗試取得某專案的 Phase 1 執行鎖;成功回 ``True``。

        - ``blocking=False``:非阻塞,立即回成敗(素材頁 / 雲端同步用)。
        - ``blocking=True`` + ``timeout``:阻塞至多 timeout 秒(編輯頁用),逾時回 ``False``。
        """
        return self._registry.lock_for(self._key(user_id, project)).acquire(
            blocking=blocking, timeout=timeout
        )

    def release(self, user_id: Optional[str], project: str) -> None:
        """釋放某專案的 Phase 1 執行鎖(允許由非取得者執行緒呼叫,見模組 docstring)。"""
        self._registry.lock_for(self._key(user_id, project)).release()


# 模組級單例:跨 API 請求、背景 job 與雲端同步共享同一組 per-project 鎖
phase1_lock = Phase1Lock()
