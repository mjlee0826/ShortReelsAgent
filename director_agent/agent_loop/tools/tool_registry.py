"""
工具註冊表 (Registry Pattern)：以 name 集中管理導演工具，供 loop 取定義與分派執行。
"""
from __future__ import annotations

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution


class ToolRegistry:
    """導演工具的註冊表：``anthropic_tools()`` 給模型、``dispatch()`` 執行。"""

    def __init__(self, tools: list[BaseTool]):
        """以工具清單建表；重複 name 後者覆蓋前者（呼叫端負責不重名）。"""
        self._tools: dict[str, BaseTool] = {tool.name: tool for tool in tools}

    def anthropic_tools(self) -> list[dict]:
        """回傳 Anthropic ``tools`` 參數（各工具的 name / description / input_schema）。"""
        return [tool.to_anthropic() for tool in self._tools.values()]

    def dispatch(self, name: str, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """依 name 分派執行；未知工具回 is_error 的 ToolExecution（讓模型自我修正）。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolExecution(content=f"未知工具：{name}", is_error=True)
        return tool.execute(tool_input, ctx)

    def has(self, name: str) -> bool:
        """是否註冊了某工具。"""
        return name in self._tools
