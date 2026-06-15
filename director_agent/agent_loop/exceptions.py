"""導演 agentic loop 的控制例外。"""
from __future__ import annotations


class ClarificationRequested(Exception):
    """
    導演呼叫 ``ask_user`` 要求中途澄清（B2 suspend）。

    由 loop 在偵測到 ask_user 後拋出：攜帶問題 / 選項與『可序列化的續跑狀態』(``resume_state``)，
    供 director_service 落地 session、發 clarification 事件、結束本 job（既有 finally 釋放生成鎖），
    之後由 ``/generate/resume`` 接答案續跑。本例外**非錯誤**，呼叫端須與一般失敗區隔處理。

    ``resume_state`` 全為可序列化內容：``system_prompt`` / ``messages``(dict 化) /
    ``pending_tool_results``(同回合非 ask 工具的結果) / ``ask_user_tool_use_id`` / ``viewed`` /
    ``corrections``。
    """

    def __init__(self, question: str, options: list, resume_state: dict):
        super().__init__(question)
        self.question = question
        self.options = options or []
        self.resume_state = resume_state
