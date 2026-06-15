"""
``correct_metadata`` 工具 (Command)：導演 view_raw 後發現畫面與 metadata 不符時，就地修正語意欄位。

修正只在本次生成 in-session 生效（寫進 :class:`AgentContext` 的 asset_index，後續 get_fields / Critic
都看修正後值），並記錄於 session。物理 / 身分欄位（以實際檔案為準）一律拒改，避免繞過 Critic 物理檢查。
"""
from __future__ import annotations

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution

# 物理 / 身分欄位（以實際檔案 ffprobe / decode 為準，不可改）
_IMMUTABLE_FIELDS = frozenset({"id", "type", "dur", "fps", "res", "width", "height"})


class CorrectMetadataTool(BaseTool):
    """就地修正素材的語意欄位（物理欄位拒改）。"""

    name = "correct_metadata"
    description = (
        "當你 view_raw 後發現畫面與某素材的 metadata 不符時，用本工具就地修正它的『語意欄位』"
        "（描述 cap / 攝影評論 critique / 情緒 mood / 場景 scene_tags / 動作 actions / 主體 subjects / "
        "視角 cam / 時段 tod 等）。物理欄位（dur / fps / res / type / id）以實際檔案為準、不可改。"
    )

    @property
    def input_schema(self) -> dict:
        """asset_id + updates(欄位→新值) + reason。"""
        return {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "要修正的素材 id"},
                "updates": {
                    "type": "object",
                    "description": "欄位 → 新值的字典（只接受語意欄位；物理欄位會被拒）",
                    "additionalProperties": True,
                },
                "reason": {"type": "string", "description": "為何要改（你在畫面上看到什麼）"},
            },
            "required": ["asset_id", "updates", "reason"],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """逐欄套用語意修正、攔阻物理欄位，回成功 / 被拒清單。"""
        asset_id = tool_input.get("asset_id", "")
        updates = tool_input.get("updates") or {}
        reason = tool_input.get("reason", "")
        if asset_id not in ctx.asset_index:
            return ToolExecution(content=f"素材 id 不存在：{asset_id}", is_error=True)

        applied: list[str] = []
        rejected: list[str] = []
        for field_name, value in updates.items():
            if field_name in _IMMUTABLE_FIELDS:
                rejected.append(field_name)
                continue
            ok, _msg = ctx.apply_correction(asset_id, field_name, value, reason)
            (applied if ok else rejected).append(field_name)

        parts: list[str] = []
        if applied:
            parts.append(f"已修正：{applied}")
        if rejected:
            parts.append(f"拒改（物理欄位不可改）：{rejected}")
        return ToolExecution(
            content="；".join(parts) or "無變更",
            narration=f"修正 {asset_id} 的 {applied}" if applied else f"修正 {asset_id}（無生效）",
        )
