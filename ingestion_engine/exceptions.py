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
