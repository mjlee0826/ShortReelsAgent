"""
Phase 4 導演 agentic tool-use loop 套件。

把舊的「固定兩階段狀態機（選角 → 單發生成 → 反思）」改造成 Claude Code 式的多輪 agentic 導演：
模型自己決定讀哪些素材的哪些欄位（``get_fields``）、必要時親看原始畫面（``view_raw``）、
修正錯誤 metadata（``correct_metadata``）、必要時問使用者（``ask_user``），最後 ``submit_blueprint``
交由 Critic 驗證、有錯把錯誤餵回同一對話就地修。

模組分工（皆 GoF 風格）：
- :mod:`agent_context`：迴圈共享可變上下文（Context Object）。
- :mod:`field_manifest`：極輕目錄 + 欄位 manifest + ``get_fields`` 投影。
- :mod:`tools`：各工具（Command）+ 註冊表（Registry）。
- :mod:`critic_gate`：submit 後的 deterministic 修補 + Critic 驗證（重用既有 ``critic/``）。
- :mod:`loop_runner`：主迴圈（Template Method）。

刻意不在本 ``__init__`` eager re-export 子模組，避免 import 時序耦合（沿用專案延遲載入慣例）。
"""
