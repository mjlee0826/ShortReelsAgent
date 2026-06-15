"""
``get_fields`` 工具 (Command)：批次投影素材的指定欄位（混合式看 metadata 的「按需深讀」）。

上層目錄只有 id / type / 一行摘要；導演要更深的欄位（情緒、逐字稿、事件索引、主體框…）時，用本工具
按需批次取，避免把整庫重欄位一次塞進 context。
"""
from __future__ import annotations

import json

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.field_manifest import project_fields
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution


class GetFieldsTool(BaseTool):
    """從素材 dossier 批次投影指定欄位，回 JSON。"""

    name = "get_fields"
    description = (
        "讀取一批素材的指定 metadata 欄位（上層目錄只有 id/type/摘要，細節用本工具按需取）。"
        "傳 asset_ids 與 fields；可用欄位見系統提供的『欄位 manifest』。一次可帶多個 id 與多個欄位。"
    )

    @property
    def input_schema(self) -> dict:
        """asset_ids + fields 兩個字串陣列。"""
        return {
            "type": "object",
            "properties": {
                "asset_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要讀的素材 id 清單（原樣照抄目錄裡的 id）",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要讀的欄位名清單（取自欄位 manifest）",
                },
            },
            "required": ["asset_ids", "fields"],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """投影並回 JSON；附帶未知欄位 / 查無 id 的警告供模型自我修正。"""
        asset_ids = tool_input.get("asset_ids") or []
        fields = tool_input.get("fields") or []
        projected, warnings = project_fields(ctx.asset_index, asset_ids, fields)
        result: dict = {"fields": projected}
        if warnings:
            result["warnings"] = warnings
        return ToolExecution(
            content=json.dumps(result, ensure_ascii=False),
            narration=f"讀取 {len(projected)} 個素材的欄位 {fields}",
        )
