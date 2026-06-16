"""
``view_template`` 工具 (Command)：讓導演親眼看範本影片的原始幀（自選或依切點取樣）。

範本不再經 Gemini 文字化（見 media_processor 的 TEMPLATE 純訊號 DAG），導演改用本工具直接看範本的
構圖 / 運鏡 / 轉場 / 剪輯節奏，自行形成風格理解。抓幀邏輯與 ``view_raw`` 共用 :mod:`frame_blocks`；
但範本只是風格參考、非成片素材，故**不**做必讀已看範圍追蹤，且取樣張數另封
``DIRECTOR_VIEW_RAW_TEMPLATE_MAX_FRAMES``（與看單一素材的 view_raw 分開計）。
"""
from __future__ import annotations

from config.director_config import DIRECTOR_VIEW_RAW_TEMPLATE_MAX_FRAMES
from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution
from director_agent.agent_loop.tools.frame_blocks import grab_video_frames, resolve_frame_timestamps

# 抓出的幀在 tool_result 內的前綴標註（讓模型知道每張圖是範本的哪一秒）
_TEMPLATE_LABEL = "範本"


class ViewTemplateTool(BaseTool):
    """抓範本影片原始幀回 base64 image blocks（不給時間點則依範本切點取樣）。"""

    name = "view_template"
    description = (
        "親眼看範本影片的原始畫面：在你給的 timestamps 秒數抓幀（不給則自動依範本場景切點取樣）。"
        "用它讀範本的構圖 / 運鏡 / 轉場 / 剪輯節奏，作為整體風格與步調參考。"
        "（範本只是風格參考，不是可用素材，clip_id 一律只能用素材目錄裡的 id。）"
    )

    @property
    def input_schema(self) -> dict:
        """timestamps（選填，秒）。"""
        return {
            "type": "object",
            "properties": {
                "timestamps": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "要抓幀的秒數清單；不給則自動依範本場景切點取樣",
                },
            },
            "required": [],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """解析範本影片實體檔，抓幀回 base64 image blocks（無範本則回 is_error）。"""
        template = ctx.template
        if not (template and template.get("abs_path")):
            return ToolExecution(content="本次生成沒有範本影片可看。", is_error=True)

        timestamps = resolve_frame_timestamps(
            tool_input.get("timestamps"), template.get("cuts"), template.get("dur"),
            DIRECTOR_VIEW_RAW_TEMPLATE_MAX_FRAMES,
        )
        try:
            blocks = grab_video_frames(template["abs_path"], _TEMPLATE_LABEL, timestamps)
        except Exception as exc:  # noqa: BLE001 - 抓幀失敗回 is_error 讓導演改時間點或放棄看範本
            return ToolExecution(content=f"讀取範本畫面失敗：{exc}", is_error=True)

        return ToolExecution(
            content=blocks,
            narration=f"親看範本 @ {[round(t, 1) for t in timestamps]}s",
        )
