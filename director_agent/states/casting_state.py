import json
import re

from config.director_config import DIRECTOR_CASTING_POOL_TARGET
from director_agent.context_compressor import ContextCompressor
from director_agent.critic.clip_id_repairer import ClipIdRepairer
from director_agent.states.base_state import BaseState
from model.managers.gemini_model_manager import GeminiModelManager
from prompt_manager.prompt_factory import PromptFactory
from prompt_manager.task_mode import TaskMode


class CastingState(BaseState):
    """
    狀態：導演選角（兩階段 Plan-then-Fill 的第一段）。

    只看精簡卡片（含逐字稿全文 + 事件視覺摘要）做『選材』——挑出真正要用的素材 id，寫進 context
    的 ``shortlist_ids`` 後轉交 ``SchedulingState``。設計目的是把上百素材的龐大 context 先收斂成少數
    選中素材，讓第二段只需對 shortlist 注入完整 dossier、回升模型對物理鐵律的遵從度。

    刻意只取 id、不帶順序 / 時長：精準排序與時間軸交給較強的精修模型在乾淨的少數素材上自由發揮，
    不讓較弱的選角模型框死它。選中的 id 沿用既有 deterministic 的 :class:`ClipIdRepairer` 校正
    raw/standardized 混淆。
    """

    def __init__(self):
        # 投影精簡卡片用（ContextCompressor 為無狀態，可就地實例化）
        self.compressor = ContextCompressor()
        # 重用既有 deterministic clip_id 修補器，校正選材的 raw/standardized 混淆
        self.repairer = ClipIdRepairer()

    def run(self, context: dict):
        print("\n[Agent State] 進入 CastingState：選材（兩階段第一段）...")

        compressed_assets = context.get("assets", [])
        # 把完整 dossier 投影成精簡卡片，exclude_none 讓圖片卡片自動去掉影片專屬欄位
        cards = self.compressor.to_casting_cards(compressed_assets)
        card_payload = [card.model_dump(exclude_none=True) for card in cards]

        gemini = GeminiModelManager()
        spec = PromptFactory.create_prompt(
            mode=TaskMode.DIRECTOR_CASTING,
            manager=gemini.prompt_manager,
            user_prompt=context.get("user_prompt", ""),
            casting_cards=card_payload,
            audio_dna=context.get("audio_dna", {}),
            template_dna=context.get("template_dna"),
        )
        # 把 schema 交給 response_schema，由 Gemini 保證輸出為合法 CastingSelection
        raw_response = gemini.generate_casting_plan(prompt=spec.text, schema=spec.schema)
        selected_ids = self._parse_selection(raw_response)

        # deterministic 校正選中的 id（raw/standardized 混淆等可唯一反查者就地修）：
        # ClipIdRepairer 吃 [{clip_id}] 形狀，故把 id 清單包一層、修完再取回
        wrapped = [{"clip_id": clip_id} for clip_id in selected_ids]
        repairs = self.repairer.repair(wrapped, compressed_assets)
        if repairs:
            print(f"🔧 [Repair] Casting 自動校正 {len(repairs)} 個 clip_id：")
            for fix in repairs:
                print(f"   - {fix}")
        repaired_ids = [item["clip_id"] for item in wrapped]

        # 篩出去重保序、且存在於素材庫的選材（杜撰 / 重複者一律剔除）
        shortlist_ids = self._resolve_shortlist(repaired_ids, context.get("asset_index", {}))

        # 防呆：選角完全失效（空 / 全部對不上素材庫）→ 不寫 shortlist，退回單階段
        #（SchedulingState 偵測不到 shortlist 即吃全部素材，保證不劣於現況）
        if not shortlist_ids:
            print("⚠️ [CastingState] 選材無有效結果，fallback 單階段（改用全部素材直接精修）。")
        else:
            # casting 只負責粗篩候選池：deterministic 收斂 / 補足成約 N 個，確保第二段有充足素材可選
            #（解決「砍太多」：模型選太多取最相關的前 N、選太少用高 aes 的未選素材補足）
            picked = len(shortlist_ids)
            shortlist_ids = self._enforce_pool_size(
                shortlist_ids, compressed_assets, DIRECTOR_CASTING_POOL_TARGET
            )
            print(
                f"🎯 [CastingState] 候選池 {len(shortlist_ids)} / {len(compressed_assets)} 個"
                f"（模型粗篩 {picked}，目標 {DIRECTOR_CASTING_POOL_TARGET}）進入精修。"
            )
            context["shortlist_ids"] = shortlist_ids

        # 不論是否 fallback，都交給 SchedulingState（它依 shortlist 有無自行分流）
        from director_agent.states.scheduling_state import SchedulingState
        return SchedulingState()

    @staticmethod
    def _resolve_shortlist(ids: list, asset_index: dict) -> list:
        """
        篩出『去重保序、且存在於素材庫』的 id 清單。

        clip_id 對不上素材庫（casting 杜撰、或 repair 後仍無解）或重複者一律剔除，確保第二段拿到的
        shortlist 不引用不存在的素材。
        """
        seen = set()
        shortlist = []
        for clip_id in ids:
            if clip_id and clip_id in asset_index and clip_id not in seen:
                seen.add(clip_id)
                shortlist.append(clip_id)
        return shortlist

    @staticmethod
    def _enforce_pool_size(selected_ids: list, compressed_assets: list, target: int) -> list:
        """
        把選材 deterministic 收斂 / 補足成約 ``target`` 個候選池。

        casting 是『粗篩』不是『定剪』：模型選太多 → 取最相關的前 ``target``（``selected_ids`` 已依
        相關性排序）；選太少 → 從未選素材中依 aes 由高到低補足，確保第二段永遠有充足素材可選
        （避免砍太多）。補進來的只是『多給選項』，最終取捨仍由第二段決定。
        """
        if len(selected_ids) >= target:
            return selected_ids[:target]
        # backfill：未選素材依 aes 由高到低補到 target（含無 id 者跳過，補進的必在素材庫內）
        chosen = set(selected_ids)
        spares = [a for a in compressed_assets if a.get("id") and a["id"] not in chosen]
        spares.sort(key=lambda a: a.get("aes") or 0.0, reverse=True)
        pool = list(selected_ids)
        for asset in spares:
            if len(pool) >= target:
                break
            pool.append(asset["id"])
        return pool

    def _parse_selection(self, text: str) -> list:
        """
        解析選角 JSON，回傳 ``selected_ids`` 清單。

        ``response_schema`` 已保證輸出為合法 CastingSelection object，故優先直接 ``json.loads`` 取
        ``selected_ids``；僅在極端情況（schema 未生效 / 被 markdown 包裹）才退回寬鬆的大括號抓取，
        維持容錯不致整批失敗（同 ``SchedulingState`` 的解析策略）。
        """
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            data = self._loose_parse(text)
        if isinstance(data, dict):
            return data.get("selected_ids", [])
        return []

    @staticmethod
    def _loose_parse(text: str):
        """fallback：schema 未生效時寬鬆抓取第一個 JSON object。"""
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f"[JSON Parse Error] 選角結果解析失敗: {e}")
        return {}
