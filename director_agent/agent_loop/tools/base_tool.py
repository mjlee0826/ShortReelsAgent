"""
導演 agentic loop 的工具基底 (Command Pattern)。

每個工具是一個 Command：宣告 ``name`` / ``description`` / ``input_schema``（給 Anthropic ``tools``
用），並實作 ``execute(tool_input, ctx)`` 回傳 :class:`ToolExecution`。loop 只認這個介面，新增工具
零侵入。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from director_agent.agent_loop.agent_context import AgentContext


@dataclass
class ToolExecution:
    """單次工具執行結果（值物件）：回給模型的 tool_result 內容 + loop 控制訊號。"""

    # tool_result 的 content：純文字工具給 str；view_raw 給 list[image content block]
    content: Any
    # 是否為錯誤結果（對應 Anthropic ``tool_result.is_error``）
    is_error: bool = False
    # 給 WS ``DIRECTOR_TOOL_CALL`` 事件的簡短中文旁白（如「精讀 clip_3 的逐字稿」）
    narration: str = ""
    # 僅 submit_blueprint 帶：模型提交的藍圖草稿（dict）；loop 據此跑 CriticGate
    submitted_blueprint: Optional[dict] = None
    # 僅 ask_user 帶：{question, options}；loop 據此序列化狀態並 raise ClarificationRequested（B2 暫停）
    clarification: Optional[dict] = None


class BaseTool(ABC):
    """所有導演工具的抽象基底（Command）。"""

    #: 工具名（對應 Anthropic tool name；須為合法識別字）
    name: str = ""
    #: 給模型看的工具說明（含「何時該用」）
    description: str = ""

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """回傳此工具的 JSON Schema（Anthropic tool 的 ``input_schema``）。"""

    @abstractmethod
    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """執行工具並回傳 :class:`ToolExecution`。"""

    def to_anthropic(self) -> dict:
        """轉成 Anthropic ``tools`` 陣列的一筆定義。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
