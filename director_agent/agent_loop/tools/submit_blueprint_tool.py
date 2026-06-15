"""
``submit_blueprint`` 工具 (Command)：導演提交最終剪輯藍圖，交由 loop 的 CriticGate 驗證。
"""
from __future__ import annotations

from prompt_manager.schemas import DirectorBlueprint

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution

# 工具名（與舊 one-shot tool use 同名，語意一致：提交藍圖）
SUBMIT_BLUEPRINT_TOOL_NAME = "submit_blueprint"


class SubmitBlueprintTool(BaseTool):
    """提交最終藍圖（DirectorBlueprint）；不在此驗證，由 loop 跑 CriticGate。"""

    name = SUBMIT_BLUEPRINT_TOOL_NAME
    description = (
        "提交最終導演剪輯藍圖（timeline + bgm_track + text_overlays）。"
        "務必在『已用 view_raw 親眼看過所有要用的素材片段』之後才呼叫。"
        "提交後系統會做物理驗證；有錯會把錯誤回給你就地修正後再次提交。"
    )

    @property
    def input_schema(self) -> dict:
        """input_schema = DirectorBlueprint 的 JSON Schema（SSOT，與舊 one-shot 同源）。"""
        return DirectorBlueprint.model_json_schema()

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """把提交的藍圖原樣帶回給 loop（loop 跑 CriticGate 後決定 terminal 或餵回）。"""
        return ToolExecution(
            content="（已收到藍圖，進行驗證中…）",
            narration="提交藍圖，進行物理驗證",
            submitted_blueprint=tool_input,
        )
