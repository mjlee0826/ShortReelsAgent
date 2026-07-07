"""
``edit_blueprint`` 工具 (Command)：微調模式的藍圖局部編輯（patch ops）。

微調（refinement）的痛點是「整份重生」：改一段的需求也要重新輸出整份 4–8k tokens 的藍圖，
且 LLM 重寫時可能誤動不該動的欄位（音樂保護 hack 的由來）。本工具改為 **ops 陣列的局部編輯**：
上一版藍圖由 facade 載入 ``ctx.blueprint_draft`` 當草稿，導演只輸出 delta（幾百 tokens），
沒被 patch 到的欄位**結構上不可能被改到**；每次套用後就地跑 :class:`CriticGate`
（deterministic 修補 + 物理驗證 + 必讀強制），錯誤立即回饋讓導演下一批 ops 修正。
最後以 ``submit_blueprint``（無參數 = 提交當前草稿）收斂，final 驗證閘不變。

僅微調模式掛載（初次生成維持一次成型的 submit —— 完整時間軸是全域約束的產物，拆步驟只會
多付回合費；見 registry 的 is_refinement 分支）。
"""
from __future__ import annotations

from copy import deepcopy

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.critic_gate import CriticGate
from director_agent.agent_loop.tools.base_tool import BaseTool, ToolExecution

# op 名稱（具名常數，避免 magic string 散落）
_OP_UPDATE_CLIP = "update_clip"
_OP_INSERT_CLIP = "insert_clip"
_OP_REMOVE_CLIP = "remove_clip"
_OP_SET_TEXT_OVERLAYS = "set_text_overlays"
_OP_UPDATE_BGM = "update_bgm"
_KNOWN_OPS = (
    _OP_UPDATE_CLIP, _OP_INSERT_CLIP, _OP_REMOVE_CLIP, _OP_SET_TEXT_OVERLAYS, _OP_UPDATE_BGM,
)


class EditBlueprintTool(BaseTool):
    """對草稿藍圖套用一批局部編輯 ops，就地驗證並回報錯誤（僅微調模式掛載）。"""

    name = "edit_blueprint"
    description = (
        "對【當前草稿藍圖】套用一批局部編輯（可一次多個 op，依序生效）："
        "update_clip（部分欄位合併進第 index 段）/ insert_clip（在 index 位置插入完整片段）/ "
        "remove_clip（刪除第 index 段）/ set_text_overlays（整批替換字幕軌）/ "
        "update_bgm（部分欄位合併進 bgm_track）。index 為 timeline 的 0 起算索引，"
        "與驗證錯誤訊息的 [N] 同一套。片段欄位結構與 submit_blueprint 的 timeline 元素相同。"
        "沒被編輯到的部分自動保留原樣。套用後系統立即做物理驗證，錯誤會回給你再修；"
        "全部改完後呼叫 submit_blueprint（不帶參數）提交草稿。"
    )

    def __init__(self):
        """持有無狀態的 CriticGate（每次套用 ops 後就地驗證草稿）。"""
        self._critic_gate = CriticGate()

    @property
    def input_schema(self) -> dict:
        """ops 陣列；clip / overlays 結構沿用 submit_blueprint schema（保持本 schema 輕量）。"""
        return {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "description": "依序套用的編輯操作清單",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": list(_KNOWN_OPS),
                                "description": "操作類型",
                            },
                            "index": {
                                "type": "integer",
                                "description": "timeline 索引（update/insert/remove 必填；0 起算）",
                            },
                            "clip": {
                                "type": "object",
                                "description": (
                                    "update_clip：要合併的部分欄位；insert_clip：完整片段"
                                    "（結構同 submit_blueprint 的 timeline 元素）"
                                ),
                            },
                            "text_overlays": {
                                "type": "array",
                                "items": {"type": "object"},
                                "description": "set_text_overlays：整批替換的字幕清單（結構同 submit_blueprint）",
                            },
                            "bgm": {
                                "type": "object",
                                "description": "update_bgm：要合併進 bgm_track 的部分欄位（如 volume / start_at）",
                            },
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["ops"],
        }

    def execute(self, tool_input: dict, ctx: AgentContext) -> ToolExecution:
        """把 ops 依序套用到草稿副本；結構性錯誤整批拒絕，套用成功即提交草稿並回驗證結果。"""
        if ctx.blueprint_draft is None:
            return ToolExecution(
                content="目前沒有草稿藍圖可編輯（本工具僅微調模式可用）。", is_error=True
            )
        ops = tool_input.get("ops")
        if not isinstance(ops, list) or not ops:
            return ToolExecution(content="ops 必須是非空陣列。", is_error=True)

        # 先在副本上套用：任一 op 結構性失敗（未知 op / 索引越界 / 缺欄位）整批原子性拒絕，
        # 草稿保持原狀 —— 避免「套了一半」讓後續 index 語意錯亂。
        draft = deepcopy(ctx.blueprint_draft)
        applied: list[str] = []
        for position, op in enumerate(ops):
            error = self._apply_one(draft, op, applied)
            if error:
                return ToolExecution(
                    content=f"ops[{position}] 套用失敗（整批未生效）：{error}", is_error=True
                )

        # 套用成功即提交草稿（草稿容許暫時性物理錯誤；submit 前仍有最終驗證閘）。
        # CriticGate 的 deterministic 修補（clip_id 反查 / 捨入夾回）會就地反映在草稿上。
        errors, repairs = self._critic_gate.validate(draft, list(ctx.asset_index.values()), ctx)
        ctx.blueprint_draft = draft

        summary = self._summarize(draft, applied, errors, repairs)
        narration = f"局部編輯 {len(applied)} 項" + (f"（{len(errors)} 個待修）" if errors else "")
        return ToolExecution(content=summary, narration=narration)

    # ── 內部：op 套用 ─────────────────────────────────────────────────────────

    def _apply_one(self, draft: dict, op: dict, applied: list[str]) -> str:
        """套用單一 op 到 draft（就地）；成功回空字串並記到 applied，失敗回錯誤訊息。"""
        if not isinstance(op, dict):
            return "op 必須是物件"
        name = op.get("op")
        timeline = draft.setdefault("timeline", [])

        if name == _OP_UPDATE_CLIP:
            index, error = self._resolve_index(op, len(timeline), allow_end=False)
            if error:
                return error
            patch = op.get("clip")
            if not isinstance(patch, dict) or not patch:
                return "update_clip 需要非空的 clip 部分欄位"
            timeline[index].update(deepcopy(patch))
            applied.append(f"update_clip[{index}]（{', '.join(patch.keys())}）")
            return ""

        if name == _OP_INSERT_CLIP:
            # insert 允許 index == len（附加到尾端）
            index, error = self._resolve_index(op, len(timeline), allow_end=True)
            if error:
                return error
            clip = op.get("clip")
            if not isinstance(clip, dict) or not clip:
                return "insert_clip 需要完整的 clip 物件"
            timeline.insert(index, deepcopy(clip))
            applied.append(f"insert_clip[{index}]（{clip.get('clip_id', '?')}）")
            return ""

        if name == _OP_REMOVE_CLIP:
            index, error = self._resolve_index(op, len(timeline), allow_end=False)
            if error:
                return error
            removed = timeline.pop(index)
            applied.append(f"remove_clip[{index}]（{removed.get('clip_id', '?')}）")
            return ""

        if name == _OP_SET_TEXT_OVERLAYS:
            overlays = op.get("text_overlays")
            if not isinstance(overlays, list):
                return "set_text_overlays 需要 text_overlays 陣列（可為空陣列 = 清空字幕）"
            draft["text_overlays"] = deepcopy(overlays)
            applied.append(f"set_text_overlays（{len(overlays)} 條）")
            return ""

        if name == _OP_UPDATE_BGM:
            patch = op.get("bgm")
            if not isinstance(patch, dict) or not patch:
                return "update_bgm 需要非空的 bgm 部分欄位"
            bgm = draft.setdefault("bgm_track", {})
            if not isinstance(bgm, dict):
                bgm = {}
                draft["bgm_track"] = bgm
            bgm.update(deepcopy(patch))
            applied.append(f"update_bgm（{', '.join(patch.keys())}）")
            return ""

        return f"未知 op：{name}（可用：{', '.join(_KNOWN_OPS)}）"

    @staticmethod
    def _resolve_index(op: dict, timeline_len: int, allow_end: bool) -> tuple[int, str]:
        """解析並檢查 index；回 ``(index, 錯誤訊息)``（成功時錯誤訊息為空字串）。"""
        index = op.get("index")
        if not isinstance(index, int):
            return -1, "缺少整數 index"
        upper = timeline_len if allow_end else timeline_len - 1
        if index < 0 or index > upper:
            return -1, f"index {index} 越界（timeline 長度 {timeline_len}）"
        return index, ""

    # ── 內部：結果摘要 ────────────────────────────────────────────────────────

    @staticmethod
    def _summarize(draft: dict, applied: list[str], errors: list, repairs: list) -> str:
        """組回給模型的套用結果：已套用清單 + 草稿概況 + 自動修補 + 待修錯誤。"""
        timeline = draft.get("timeline") or []
        # 草稿概況給 end_at 尾值當總長參考（timeline 空則 0）
        last_end = timeline[-1].get("end_at", 0.0) if timeline else 0.0
        lines = [
            "已套用：" + "；".join(applied),
            f"草稿現況：timeline {len(timeline)} 段（尾段 end_at={last_end}）、"
            f"text_overlays {len(draft.get('text_overlays') or [])} 條。",
        ]
        if repairs:
            lines.append("系統自動修補：" + "；".join(repairs))
        if errors:
            lines.append(
                "⚠️ 草稿目前未通過物理驗證（可繼續編輯，submit 前須修完；索引 [N] 為 timeline 第 N 段）：\n"
                + "\n".join(f"- {err}" for err in errors)
            )
        else:
            lines.append("✅ 草稿通過物理驗證，可 submit_blueprint（不帶參數）提交。")
        return "\n".join(lines)
