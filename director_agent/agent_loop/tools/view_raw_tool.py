"""
``view_raw`` 工具 (Command)：讓導演親眼看素材的原始畫面（必讀原素材的執行端）。

圖片：直接讀檔降解析回 base64；影片：在指定時間點（或預設場景切點 / 均勻取樣）抓關鍵幀,
多幀拼成一張 montage（見 :mod:`frame_blocks`,像素 token 約 3–4× 省）。支援**一次看多個素材**
（``requests`` 陣列）：N 個素材一次呼叫就一輪 API 往返,省掉逐素材往返的重複 context 讀取與
快取寫入費；總幀數以 ``DIRECTOR_VIEW_RAW_MAX_TOTAL_FRAMES`` 封頂,超出部分提示分批再看。
導演據回傳畫面確認構圖 / 主體 / 與 metadata 是否相符,並把「已親看的時間範圍」記進
:class:`AgentContext`,供 submit 後的必讀強制驗證。
"""
from __future__ import annotations

from config.director_config import (
    DIRECTOR_VIEW_RAW_MAX_FRAMES,
    DIRECTOR_VIEW_RAW_MAX_TOTAL_FRAMES,
)
from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution
from director_agent.agent_loop.tools.frame_blocks import (
    build_video_frame_blocks,
    image_block,
    resolve_frame_timestamps,
    text_block,
)


class ViewRawTool(BaseTool):
    """讀素材原始畫面（圖片整張 / 影片抓幀拼格）回 base64 image blocks；可一次看多個素材。"""

    name = "view_raw"
    description = (
        "親眼看素材的原始畫面：圖片回整張、影片抓關鍵幀拼成一張網格圖（各格左上有 #編號與秒數，"
        "並附秒數對照表）。可一次帶多個素材（requests 陣列）省往返；影片可逐素材指定 timestamps "
        "秒數（不給則自動取樣關鍵幀）。"
        "【必讀】任何你打算放進成片的素材，submit_blueprint 前都必須先用本工具看過對應片段；"
        "看到與 metadata 不符時用 correct_metadata 修正。"
    )

    @property
    def input_schema(self) -> dict:
        """requests：[{asset_id 必填, timestamps 影片選填（秒）}, ...]。"""
        return {
            "type": "object",
            "properties": {
                "requests": {
                    "type": "array",
                    "description": "要看的素材清單（可一次多個，省 API 往返）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "asset_id": {
                                "type": "string",
                                "description": "素材 id（原樣照抄目錄裡的 id）",
                            },
                            "timestamps": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "影片要抓幀的秒數清單（圖片忽略）；不給則自動取樣關鍵幀",
                            },
                        },
                        "required": ["asset_id"],
                    },
                },
            },
            "required": ["requests"],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """逐素材抓幀 / 讀圖組 blocks 並記錄已親看範圍；部分失敗不連坐（僅全數失敗回 is_error）。"""
        requests = self._normalize_requests(tool_input)
        if not requests:
            return ToolExecution(content="缺少 requests：請帶要看的素材 id 清單。", is_error=True)

        blocks: list[dict] = []
        narrations: list[str] = []
        failures: list[str] = []
        # 單次呼叫總幀數預算：多素材批次看要封頂,避免一次看整庫把 context 撐爆
        frame_budget = DIRECTOR_VIEW_RAW_MAX_TOTAL_FRAMES

        for request in requests:
            asset_id = request.get("asset_id", "")
            dossier = ctx.asset_index.get(asset_id)
            if dossier is None:
                failures.append(f"素材 id 不存在：{asset_id}")
                continue
            if frame_budget <= 0:
                blocks.append(text_block(
                    f"（總幀數已達單次上限 {DIRECTOR_VIEW_RAW_MAX_TOTAL_FRAMES}，"
                    f"{asset_id} 之後的素材請下一次呼叫再看。）"
                ))
                break
            try:
                used = self._view_one(request, dossier, ctx, frame_budget, blocks, narrations)
            except Exception as exc:  # noqa: BLE001 - 單素材失敗記入清單,不連坐其他素材
                failures.append(f"讀取畫面失敗（{asset_id}）：{exc}")
                continue
            frame_budget -= used

        if not blocks and failures:
            return ToolExecution(content="；".join(failures), is_error=True)
        # 部分失敗：把失敗訊息附在畫面後,導演可換素材 / 改時間點
        for failure in failures:
            blocks.append(text_block(f"⚠️ {failure}"))
        return ToolExecution(content=blocks, narration="；".join(narrations))

    # ── 內部 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_requests(tool_input: dict) -> list[dict]:
        """正規化輸入：canonical 為 ``requests`` 陣列；相容單素材舊形（asset_id + timestamps）。"""
        requests = tool_input.get("requests")
        if isinstance(requests, list) and requests:
            return [r for r in requests if isinstance(r, dict)]
        if tool_input.get("asset_id"):
            return [{"asset_id": tool_input["asset_id"], "timestamps": tool_input.get("timestamps")}]
        return []

    def _view_one(
        self,
        request: dict,
        dossier: dict,
        ctx: AgentContext,
        frame_budget: int,
        blocks: list[dict],
        narrations: list[str],
    ) -> int:
        """看單一素材：blocks / narrations 就地累加,回傳本素材消耗的幀數。"""
        # 延遲載入重型相依（PIL），使無此套件的環境仍可載入本模組
        from PIL import Image

        from backend.utils.asset_discovery import to_abs_path

        asset_id = request["asset_id"]
        abs_path = to_abs_path(ctx.project_dir, asset_id)

        if dossier.get("type") == "video":
            timestamps = resolve_frame_timestamps(
                request.get("timestamps"), dossier.get("cuts"), dossier.get("dur"),
                min(DIRECTOR_VIEW_RAW_MAX_FRAMES, frame_budget),
            )
            blocks.extend(build_video_frame_blocks(abs_path, asset_id, timestamps))
            span_start, span_end = (min(timestamps), max(timestamps)) if timestamps else (0.0, 0.0)
            ctx.record_view(asset_id, span_start, span_end)
            narrations.append(f"親看 {asset_id} @ {[round(t, 1) for t in timestamps]}s")
            return len(timestamps)

        pil_image = Image.open(abs_path).convert("RGB")
        blocks.extend([text_block(f"{asset_id}（整張）："), image_block(pil_image)])
        ctx.record_view(asset_id, 0.0, 0.0)
        narrations.append(f"親看圖片 {asset_id}")
        return 1
