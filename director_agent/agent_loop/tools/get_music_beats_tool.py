"""
``get_music_beats`` 工具 (Command)：導演要卡點時，取得背景準備好的配樂節拍（music ∥ loop 重疊）。

配樂下載 + 節拍分析在背景 future 跑（與導演讀素材重疊）。導演決定剪輯點前呼叫本工具 join 該 future
（或 resume 時讀 facade 重載的 ctx.audio_dna），取得 beats / onsets / bpm + 曲目摘要。配樂為 none /
取得失敗 → 回「無配樂」，導演不需卡點。
"""
from __future__ import annotations

import json

from config.director_config import DIRECTOR_MUSIC_FUTURE_TIMEOUT_SECONDS
from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution


class GetMusicBeatsTool(BaseTool):
    """取得背景準備的配樂節拍（join future 或 resume 的 ctx.audio_dna）。"""

    name = "get_music_beats"
    description = (
        "取得本片配樂的節拍資訊（beats / onsets / bpm）供卡點。配樂在背景準備，本工具會等它備妥。"
        "決定剪輯點 / 卡點前呼叫；配樂可能為 none（回『無配樂』，則不需卡點）。"
    )

    @property
    def input_schema(self) -> dict:
        """無參數。"""
        return {"type": "object", "properties": {}}

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """join 背景 future（或讀 resume 的 ctx.audio_dna），回 analysis + 曲目摘要 JSON。"""
        # resume 時 ctx.audio_dna 已由 facade 設好；首跑則 join 背景 future
        if ctx.audio_dna is None and ctx.music_future is not None:
            try:
                ctx.audio_dna = ctx.music_future.result(
                    timeout=DIRECTOR_MUSIC_FUTURE_TIMEOUT_SECONDS
                ) or {}
            except Exception as exc:  # noqa: BLE001 - 配樂備妥失敗不擋導演，回無配樂續剪
                ctx.audio_dna = {}
                return ToolExecution(
                    content=f"配樂準備失敗（{exc}），本片不卡點、不加 BGM。",
                    narration="配樂準備失敗，改不卡點",
                )

        audio_dna = ctx.audio_dna or {}
        analysis = audio_dna.get("analysis") if isinstance(audio_dna, dict) else None
        if not analysis:
            return ToolExecution(content="本片無配樂（none），不需卡點。", narration="無配樂")

        result = {
            "bpm": analysis.get("bpm"),
            "beats": analysis.get("beats", []),
            "onsets": analysis.get("onsets", []),
            "query": audio_dna.get("query", ""),
        }
        return ToolExecution(
            content=json.dumps(result, ensure_ascii=False),
            narration=f"取得配樂節拍（bpm={result.get('bpm')}）",
        )
