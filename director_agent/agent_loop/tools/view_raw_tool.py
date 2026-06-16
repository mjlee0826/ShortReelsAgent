"""
``view_raw`` 工具 (Command)：讓導演親眼看素材的原始畫面（必讀原素材的執行端）。

圖片：直接讀檔降解析回 base64；影片：在指定時間點（或預設場景切點 / 均勻取樣）抓關鍵幀回 base64。
回傳 image content blocks 當 tool_result，導演據此確認構圖 / 主體 / 與 metadata 是否相符，並把「已親看
的時間範圍」記進 :class:`AgentContext`，供 submit 後的必讀強制驗證。

抓幀 / 降解析 / 取樣的低階邏輯與 ``view_template`` 共用 :mod:`frame_blocks`（重型相依 cv2 / PIL 於其內
延遲 import，使本模組在無這些套件的環境仍可被結構性載入）。
"""
from __future__ import annotations

from config.director_config import DIRECTOR_VIEW_RAW_MAX_FRAMES
from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution
from director_agent.agent_loop.tools.frame_blocks import (
    grab_video_frames,
    image_block,
    resolve_frame_timestamps,
    text_block,
)


class ViewRawTool(BaseTool):
    """讀素材原始畫面（圖片整張 / 影片抓幀）回 base64 image blocks。"""

    name = "view_raw"
    description = (
        "親眼看某素材的原始畫面：圖片回整張、影片在你給的 timestamps 秒數抓關鍵幀（不給則自動取樣）。"
        "【必讀】任何你打算放進成片的素材，submit_blueprint 前都必須先用本工具看過對應片段；"
        "看到與 metadata 不符時用 correct_metadata 修正。"
    )

    @property
    def input_schema(self) -> dict:
        """asset_id（必填）+ timestamps（影片選填，秒）。"""
        return {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "要看的素材 id（原樣照抄目錄裡的 id）"},
                "timestamps": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "影片要抓幀的秒數清單（圖片忽略）；不給則自動取樣關鍵幀",
                },
            },
            "required": ["asset_id"],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """解析素材實體檔，抓幀 / 讀圖降解析回 base64 image blocks，並記錄已親看範圍。"""
        # 延遲載入重型相依（PIL），使無此套件的環境仍可載入本模組
        from PIL import Image

        from backend.utils.asset_discovery import to_abs_path

        asset_id = tool_input.get("asset_id", "")
        dossier = ctx.asset_index.get(asset_id)
        if dossier is None:
            return ToolExecution(content=f"素材 id 不存在：{asset_id}", is_error=True)

        abs_path = to_abs_path(ctx.project_dir, asset_id)
        try:
            if dossier.get("type") == "video":
                timestamps = resolve_frame_timestamps(
                    tool_input.get("timestamps"), dossier.get("cuts"), dossier.get("dur"),
                    DIRECTOR_VIEW_RAW_MAX_FRAMES,
                )
                blocks = grab_video_frames(abs_path, asset_id, timestamps)
                span_start, span_end = (min(timestamps), max(timestamps)) if timestamps else (0.0, 0.0)
                ctx.record_view(asset_id, span_start, span_end)
                narration = f"親看 {asset_id} @ {[round(t, 1) for t in timestamps]}s"
            else:
                pil_image = Image.open(abs_path).convert("RGB")
                blocks = [text_block(f"{asset_id}（整張）："), image_block(pil_image)]
                ctx.record_view(asset_id, 0.0, 0.0)
                narration = f"親看圖片 {asset_id}"
        except Exception as exc:  # noqa: BLE001 - 抓幀 / 讀圖失敗回 is_error 讓導演換素材或改時間點
            return ToolExecution(content=f"讀取畫面失敗（{asset_id}）：{exc}", is_error=True)

        return ToolExecution(content=blocks, narration=narration)
