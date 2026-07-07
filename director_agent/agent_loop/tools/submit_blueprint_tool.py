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
    """提交最終藍圖（DirectorBlueprint）；不在此驗證，由 loop 跑 CriticGate。

    微調模式（``draft_mode=True``）下建議**不帶參數**提交：直接送出 ``ctx.blueprint_draft``
    （edit_blueprint 的編輯結果），避免整份藍圖重新輸出一遍（token 與誤改風險皆省）。
    """

    name = SUBMIT_BLUEPRINT_TOOL_NAME

    def __init__(self, draft_mode: bool = False):
        """``draft_mode``：微調模式，允許（且建議）無參數提交當前草稿。"""
        self._draft_mode = draft_mode

    @property
    def description(self) -> str:  # type: ignore[override]
        """依模式給不同引導：微調模式主打無參數提交草稿。"""
        base = (
            "提交最終導演剪輯藍圖（timeline + bgm_track + text_overlays）。"
            "務必在『已用 view_raw 親眼看過所有要用的素材片段』之後才呼叫。"
            "提交後系統會做物理驗證；有錯會把錯誤回給你就地修正後再次提交。"
        )
        if self._draft_mode:
            base += (
                "【微調模式】請**不帶參數**呼叫＝提交 edit_blueprint 編輯後的當前草稿"
                "（不要整份重新輸出藍圖）。"
            )
        return base

    @property
    def input_schema(self) -> dict:
        """input_schema = DirectorBlueprint 的 JSON Schema（SSOT，與舊 one-shot 同源）。"""
        return DirectorBlueprint.model_json_schema()

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """把提交的藍圖帶回給 loop（loop 跑 CriticGate 後決定 terminal 或餵回）。

        微調模式且未帶 timeline 時提交當前草稿（edit_blueprint 的編輯結果）。
        """
        blueprint = tool_input
        if self._draft_mode and not tool_input.get("timeline"):
            if ctx.blueprint_draft is None:
                return ToolExecution(
                    content="沒有草稿可提交：請先用 edit_blueprint 編輯、或帶完整藍圖提交。",
                    is_error=True,
                )
            blueprint = ctx.blueprint_draft
        return ToolExecution(
            content="（已收到藍圖，進行驗證中…）",
            narration="提交藍圖，進行物理驗證",
            submitted_blueprint=blueprint,
        )
