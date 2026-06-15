"""
``ask_user`` 工具 (Command)：導演中途向使用者提問以對齊（B2 suspend/resume 的觸發端）。

本工具不直接暫停：``execute`` 回傳帶 ``clarification`` 的 :class:`ToolExecution`，由 loop 統一在
處理完同回合其餘工具後序列化狀態並拋 :class:`ClarificationRequested`，交 director_service 落地 session。
"""
from __future__ import annotations

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution


class AskUserTool(BaseTool):
    """向使用者提問並暫停生成（B2）。"""

    name = "ask_user"
    description = (
        "當你需要使用者拍板才能繼續（風格走向 / 重要取捨 / 缺關鍵資訊）時，用本工具提問並暫停生成。"
        "問題要具體，必要時給 options 讓使用者點選。系統會暫停、等使用者回答後再續跑——"
        "別為枝微末節而問（命名 / 預設值 / 等價選項等小決策自己合理決定即可）。"
    )

    @property
    def input_schema(self) -> dict:
        """question（必填）+ options（選填，給使用者點選）。"""
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要問使用者的具體問題"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "（選填）讓使用者點選的選項",
                },
            },
            "required": ["question"],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """回傳帶 clarification 的執行結果（不在此暫停，由 loop 統一處理）。"""
        question = tool_input.get("question", "")
        options = tool_input.get("options") or []
        return ToolExecution(
            content="（問題已送出，等待使用者回答）",
            narration=f"向使用者提問：{question}",
            clarification={"question": question, "options": options},
        )
