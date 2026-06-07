"""
Phase 1 執行互斥鎖 (Keyed Lock Registry + Facade)。

``run_phase1``(標準化 + 感知 pipeline + 落地 metadata/status)有四個進入點:雲端同步背景
預跑、編輯頁完整生成、素材頁「重新分析」與「開始生成」。四者對同一專案併發跑會造成:
phase1 metadata/status 併發寫遺失更新、雙重佔用 GPU(共用機易 OOM)、dirty/已分析基準互踩。

本模組提供 per-(user, project) 的執行鎖,讓四條路徑對同一專案的 Phase 1 真正互斥:
- 素材頁兩顆按鈕:非阻塞 try,搶不到即由端點回 409(避免重複觸發堆積)。
- 編輯頁:阻塞等待(帶 timeout),等前景做完再讀新鮮快取。
- 雲端同步:非阻塞 try,搶不到即略過本輪(下輪 poller 重試)。

本鎖刻意與 ``CloudIngestionService`` 的同步鎖分開:同步鎖序列化同一專案的併發同步;本鎖則涵蓋
雲端同步的「下載 + 標準化(+ 自動分析)」ingest 段、編輯頁完整生成、素材頁兩顆按鈕的 Phase 1。
雲端同步取鎖順序恆為「同步鎖 → 本鎖」且永不反向(其餘進入點只取本鎖),無死鎖之虞。

``threading.Lock.release()`` 允許由「非取得者執行緒」呼叫(CPython 明文支援),故素材頁可在
async 端點(event loop 執行緒)取鎖、於背景 worker thread 的 ``finally`` 釋放(以 Lock 當 gate)。

持鎖者可標註「目前在做什麼」(activity):雲端同步的下載 / 標準化段標 ingesting、實際 Phase 1
分析段標 analyzing。搶不到鎖的呼叫端(素材頁端點)據此回不同的 409 訊息(處理素材 vs 分析中)。
"""
from __future__ import annotations

import threading
from typing import Optional

# 取鎖失敗 / 逾時時的使用者面向訊息(集中管理,禁 magic string 散落)
PHASE1_BUSY_MESSAGE = "素材分析中，請稍候"      # 持鎖者在跑 Phase 1 分析:端點回 409
INGEST_BUSY_MESSAGE = "正在處理素材，請稍候"     # 持鎖者在下載 / 標準化素材:端點回 409
EDITOR_BUSY_MESSAGE = "分析進行中，請稍候再試"   # 編輯頁:等待前景逾時

# 持鎖活動標籤(具名常數):供搶不到鎖者判斷該回哪一種 409 訊息
PHASE1_ACTIVITY_ANALYZING = "analyzing"   # 實際 Phase 1 感知分析(預設)
PHASE1_ACTIVITY_INGESTING = "ingesting"   # 雲端同步的下載 / 標準化段

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
        """初始化底層鍵控鎖登錄表與各 key 的持鎖活動標籤對照。"""
        self._registry = KeyedLockRegistry()
        # {鎖鍵: 目前持鎖者宣告的活動}(analyzing / ingesting);僅在持鎖期間有意義
        self._activities: dict[str, str] = {}
        self._activities_guard = threading.Lock()

    @staticmethod
    def _key(user_id: Optional[str], project: str) -> str:
        """組鎖鍵;user_id 可能為 None(CLI / 無認證),以固定前綴避免與真實 user 撞鍵。"""
        return f"{user_id or '_anon'}/{project}"

    def acquire(self, user_id: Optional[str], project: str, *,
                blocking: bool = True, timeout: float = _NO_TIMEOUT,
                activity: str = PHASE1_ACTIVITY_ANALYZING) -> bool:
        """
        嘗試取得某專案的 Phase 1 執行鎖;成功回 ``True`` 並記錄持鎖活動。

        - ``blocking=False``:非阻塞,立即回成敗(素材頁 / 雲端同步用)。
        - ``blocking=True`` + ``timeout``:阻塞至多 timeout 秒(編輯頁用),逾時回 ``False``。
        - ``activity``:本次持鎖在做什麼(預設 analyzing);供搶不到鎖者選 409 訊息,
          雲端同步的下載 / 標準化段傳 ``ingesting``。
        """
        key = self._key(user_id, project)
        acquired = self._registry.lock_for(key).acquire(blocking=blocking, timeout=timeout)
        if acquired:
            with self._activities_guard:
                self._activities[key] = activity
        return acquired

    def release(self, user_id: Optional[str], project: str) -> None:
        """釋放某專案的 Phase 1 執行鎖並清除其活動標籤(允許由非取得者執行緒呼叫,見模組 docstring)。"""
        key = self._key(user_id, project)
        # 先清活動標籤再釋放鎖:釋放後該標籤已無意義,留著會誤導下一個搶不到鎖者
        with self._activities_guard:
            self._activities.pop(key, None)
        self._registry.lock_for(key).release()

    def set_activity(self, user_id: Optional[str], project: str, activity: str) -> None:
        """
        更新某專案「目前持鎖者」宣告的活動(須由持鎖者呼叫);供持鎖期間階段切換時更新 409 訊息。

        例:雲端同步以 ingesting 取鎖涵蓋下載/標準化,真正進入感知分析時翻成 analyzing,讓搶不到鎖者
        看到的訊息與當下階段一致。僅在仍持鎖(有活動記錄)時更新,避免覆寫已釋放專案的狀態。
        """
        key = self._key(user_id, project)
        with self._activities_guard:
            if key in self._activities:
                self._activities[key] = activity

    def current_activity(self, user_id: Optional[str], project: str) -> Optional[str]:
        """
        回傳某專案「目前持鎖者」宣告的活動(analyzing / ingesting);無人持鎖回 ``None``。

        供搶不到鎖的素材頁端點判斷該回哪一種 409 訊息。持鎖者剛釋放的瞬間可能讀到 ``None``
        (良性競態),呼叫端對未知值退回預設分析中訊息即可。
        """
        with self._activities_guard:
            return self._activities.get(self._key(user_id, project))


# 模組級單例:跨 API 請求、背景 job 與雲端同步共享同一組 per-project 鎖
phase1_lock = Phase1Lock()
