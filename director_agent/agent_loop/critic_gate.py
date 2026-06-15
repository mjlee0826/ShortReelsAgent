"""
Submit 後的把關（重用既有 ``critic/``）：deterministic 修補 + Critic 物理驗證。

把舊 ``ReflectionState`` 的「驗證前 deterministic 修補 → Critic 驗證」邏輯搬進 agentic loop：導演
``submit_blueprint`` 後，先以 ``ClipIdRepairer`` / ``ClipDurationRepairer`` 就地修可確定的身分 / 捨入
溢位，再跑 ``CriticManager`` 全責任鏈；回 ``(錯誤清單, 修補紀錄)``。錯誤非空時由 loop 把錯誤當
tool_result 餵回同一對話讓導演就地修（取代舊的 bounce 回新 state，保留上下文）。

必讀強制（ViewedBeforeUseValidator）於 Phase B 併入本閘。
"""
from __future__ import annotations

from typing import Optional

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.critic.base_validator import BaseValidator
from director_agent.critic.clip_duration_repairer import ClipDurationRepairer
from director_agent.critic.clip_id_repairer import ClipIdRepairer
from director_agent.critic.critic_manager import CriticManager


class ViewedBeforeUseValidator(BaseValidator):
    """
    必讀強制（決策 5）：timeline / pip 的每個 ``clip_id`` 必須在重疊時間範圍被 ``view_raw`` 過，否則
    回錯誤逼導演先親看。需要 :class:`AgentContext` 的「已看範圍」，故由 :class:`CriticGate` 在 ctx 可用時
    才掛入（不進無狀態的 ``CriticManager`` 責任鏈）。
    """

    def __init__(self, ctx: AgentContext):
        """注入持有已看範圍的 agentic 上下文。"""
        self.ctx = ctx

    def validate(self, timeline: list, assets: list) -> list:
        """逐片段（含 pip_video）檢查是否已親看過要用的區間，回未親看的錯誤清單。"""
        asset_map = {a["id"]: a for a in assets if a.get("id")}
        errors: list = []
        for index, clip in enumerate(timeline):
            errors += self._check(
                index, clip.get("clip_id"),
                clip.get("source_start", 0.0), clip.get("source_end", 0.0), asset_map, "",
            )
            pip = clip.get("pip_video")
            if isinstance(pip, dict):
                errors += self._check(
                    index, pip.get("clip_id"),
                    pip.get("source_start", 0.0), pip.get("source_start", 0.0), asset_map, ".pip_video",
                )
        return errors

    def _check(self, index, clip_id, src_start, src_end, asset_map, suffix) -> list:
        """單一 clip_id 的必讀檢查；身分錯誤交 ClipIdRepairer / Critic，不在此重複報。"""
        asset = asset_map.get(clip_id)
        if asset is None:
            return []
        is_video = asset.get("type") == "video"
        viewed = (
            self.ctx.was_viewed(clip_id, src_start, src_end)
            if is_video else self.ctx.was_viewed(clip_id, 0.0, 0.0)
        )
        if viewed:
            return []
        span = f" [{src_start}, {src_end}]s" if is_video else ""
        return [
            f"Clip [{index}]{suffix} ({clip_id}): 尚未用 view_raw 親看過{span}的畫面就要使用——"
            "請先 view_raw 確認再 submit_blueprint"
        ]


class CriticGate:
    """submit 草稿的 deterministic 修補 + Critic 物理驗證 + 必讀強制閘（重用既有元件）。"""

    def __init__(self):
        """實例化責任鏈 Critic 與兩個 deterministic 修補器（皆無狀態，可重用）。"""
        self.critic = CriticManager()
        self.id_repairer = ClipIdRepairer()
        self.duration_repairer = ClipDurationRepairer()

    def validate(
        self, blueprint: dict, compressed_assets: list, ctx: Optional[AgentContext] = None
    ) -> tuple[list, list]:
        """
        對提交的藍圖跑「修補 → 物理驗證 → 必讀強制」，回 ``(errors, repairs)``。

        就地修補 ``blueprint['timeline']``（clip_id 反查 / source_end 捨入夾回），故修補會反映在最終
        藍圖；接著跑 ``CriticManager`` 物理驗證。``ctx`` 非空時再掛 :class:`ViewedBeforeUseValidator`
        做必讀強制（置於 clip_id 修補之後，確保以修好的 id 比對已看素材）。timeline 缺失 / 非陣列 →
        回單一嚴重錯誤（與舊行為一致）。
        """
        timeline = blueprint.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            return ["嚴重錯誤：未提交有效的 timeline 陣列。"], []

        repairs: list = []
        repairs += self.id_repairer.repair(timeline, compressed_assets)
        repairs += self.duration_repairer.repair(timeline, compressed_assets)
        errors = self.critic.validate_all(timeline, compressed_assets)
        if ctx is not None:
            errors += ViewedBeforeUseValidator(ctx).validate(timeline, compressed_assets)
        return errors, repairs
