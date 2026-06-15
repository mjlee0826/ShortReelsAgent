"""
``view_raw`` 工具 (Command)：讓導演親眼看素材的原始畫面（必讀原素材的執行端）。

圖片：直接讀檔降解析回 base64；影片：在指定時間點（或預設場景切點 / 均勻取樣）抓關鍵幀回 base64。
回傳 image content blocks 當 tool_result，導演據此確認構圖 / 主體 / 與 metadata 是否相符，並把「已親看
的時間範圍」記進 :class:`AgentContext`，供 submit 後的必讀強制驗證。

重型相依（cv2 / PIL）刻意延遲到 ``execute`` 內 import，使本模組在無這些套件的環境仍可被結構性載入。
"""
from __future__ import annotations

import base64
from io import BytesIO

from config.director_config import (
    DIRECTOR_VIEW_RAW_DOWNSCALE_PX,
    DIRECTOR_VIEW_RAW_MAX_FRAMES,
)
from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution

# tool_result image block 的 JPEG MIME
_JPEG_MEDIA_TYPE = "image/jpeg"
# JPEG 壓縮品質（control base64 大小 / token）
_JPEG_QUALITY = 85


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
        # 延遲載入重型相依（PIL / cv2），使無這些套件的環境仍可載入本模組
        from PIL import Image

        from backend.utils.asset_discovery import to_abs_path

        asset_id = tool_input.get("asset_id", "")
        dossier = ctx.asset_index.get(asset_id)
        if dossier is None:
            return ToolExecution(content=f"素材 id 不存在：{asset_id}", is_error=True)

        abs_path = to_abs_path(ctx.project_dir, asset_id)
        try:
            if dossier.get("type") == "video":
                timestamps = _resolve_timestamps(tool_input.get("timestamps"), dossier)
                blocks = self._grab_video_frames(abs_path, asset_id, timestamps)
                span_start, span_end = (min(timestamps), max(timestamps)) if timestamps else (0.0, 0.0)
                ctx.record_view(asset_id, span_start, span_end)
                narration = f"親看 {asset_id} @ {[round(t, 1) for t in timestamps]}s"
            else:
                pil_image = Image.open(abs_path).convert("RGB")
                blocks = [self._text_block(f"{asset_id}（整張）："), self._image_block(pil_image)]
                ctx.record_view(asset_id, 0.0, 0.0)
                narration = f"親看圖片 {asset_id}"
        except Exception as exc:  # noqa: BLE001 - 抓幀 / 讀圖失敗回 is_error 讓導演換素材或改時間點
            return ToolExecution(content=f"讀取畫面失敗（{asset_id}）：{exc}", is_error=True)

        return ToolExecution(content=blocks, narration=narration)

    # ── 內部工具 ──────────────────────────────────────────────────────────────
    def _grab_video_frames(self, abs_path: str, asset_id: str, timestamps: list[float]) -> list[dict]:
        """在指定時間點逐一抓幀，回 content blocks（text 標註 + image）；全抓不到則拋。"""
        from media_processor.pipeline.utils.video_frame_utils import grab_frame_at_time

        blocks: list[dict] = []
        for timestamp in timestamps:
            pil_image = grab_frame_at_time(abs_path, timestamp)
            if pil_image is None:
                continue
            blocks.append(self._text_block(f"{asset_id} @ {round(timestamp, 2)}s："))
            blocks.append(self._image_block(pil_image))
        if not blocks:
            raise RuntimeError("所有時間點都抓不到幀")
        return blocks

    @staticmethod
    def _text_block(text: str) -> dict:
        """組一個 text content block。"""
        return {"type": "text", "text": text}

    @staticmethod
    def _image_block(pil_image) -> dict:
        """把 PIL Image 降解析、轉 JPEG base64，組成 image content block。"""
        image = pil_image.copy()
        image.thumbnail((DIRECTOR_VIEW_RAW_DOWNSCALE_PX, DIRECTOR_VIEW_RAW_DOWNSCALE_PX))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
        data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": _JPEG_MEDIA_TYPE, "data": data},
        }


def _resolve_timestamps(requested, dossier: dict) -> list[float]:
    """
    決定影片要抓幀的秒數（最多 ``DIRECTOR_VIEW_RAW_MAX_FRAMES`` 張）。

    給了 timestamps 就用（截斷上限）；否則優先用場景切點 cuts，再退回 dur 內均勻取樣，最後給中點。
    """
    max_frames = DIRECTOR_VIEW_RAW_MAX_FRAMES
    if requested:
        return [float(t) for t in requested][:max_frames]

    cuts = dossier.get("cuts") or []
    if cuts:
        return [float(t) for t in cuts][:max_frames]

    dur = float(dossier.get("dur") or 0.0)
    if dur <= 0:
        return [0.0]
    # 均勻取樣（避開頭尾）：dur*(k+1)/(n+1)
    return [round(dur * (k + 1) / (max_frames + 1), 2) for k in range(max_frames)]
