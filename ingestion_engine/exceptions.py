"""
攝取層例外階層 (Exception Hierarchy)。

把雲端存取的錯誤語意收斂成三類，與底層實作（Drive API / 未來其他雲端）解耦：
呼叫端只依「授權失效」與「一般存取錯誤」做不同處置，不需知道底層 HTTP 細節。
`RemoteAuthError` 為 `RemoteAccessError` 子類，故同步協調層「先接授權、再接一般存取」
的攔截順序得以成立（授權失效暫停該 project，其餘暫時性錯誤下輪重試）。
"""
from __future__ import annotations


class IngestionError(Exception):
    """攝取層錯誤基底。"""


class RemoteAccessError(IngestionError):
    """一般雲端存取錯誤：HTTP 非 2xx、回應解析失敗、網路問題、逾時等（暫時性，下輪重試）。"""


class RemoteAuthError(RemoteAccessError):
    """授權／權限失效：401／403、資料夾被轉為私人、API key 無權；呼叫端據此暫停該 project 同步。"""


class Phase1DeferredError(IngestionError):
    """
    同步觸發的 Phase 1 因「前景已有 Phase 1 在跑同一專案」(編輯頁 / 素材頁持鎖)而略過本輪。

    非錯誤、非授權問題:由注入的 phase1_runner 在搶不到執行鎖時拋出,`_reconcile` 據此「不前進
    簽章、不標 failed」並保留待分析狀態,讓下輪 poller(簽章仍未收斂)重試,避免雙重佔用 GPU。
    """
