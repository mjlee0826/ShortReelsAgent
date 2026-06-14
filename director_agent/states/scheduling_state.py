from director_agent.states.base_state import BaseState
from model.managers.director_provider import get_director_manager
from prompt_manager.prompt_factory import PromptFactory
from prompt_manager.task_mode import TaskMode
from shared.json_utils import parse_json_lenient

class SchedulingState(BaseState):
    
    def run(self, context: dict):
        # 兩階段模式：CastingState 已選好 shortlist → 第二段只把『選中素材的完整 dossier』餵進精修，
        # 排序 / 時間軸 / 剪輯全由本階段自由決定；單階段（無 shortlist）維持原本傳全部素材（零回歸）。
        assets = context.get("assets", [])
        shortlist_ids = context.get("shortlist_ids")
        if shortlist_ids:
            asset_index = context.get("asset_index", {})
            assets = [asset_index[clip_id] for clip_id in shortlist_ids if clip_id in asset_index]
            print(f"\n[Agent State] 導演精修生成藍圖（兩階段第二段；{len(assets)} 個選中素材）...")
        else:
            print("\n[Agent State] 正在呼叫高強度導演模型生成藍圖...")
        
        # 依 DIRECTOR_PROVIDER 取得導演 manager（預設 Claude，可 env 切回 Gemini 做 A/B）
        manager = get_director_manager()
        
        # 透過 PromptFactory 請求 PromptSpec(文字 + 結構化輸出 schema)
        spec = PromptFactory.create_prompt(
            mode=TaskMode.DIRECTOR_BLUEPRINT,
            manager=manager.prompt_manager,
            user_prompt=context.get("user_prompt", ""),
            assets=assets,
            template_dna=context.get("template_dna"),
            previous_timeline=context.get("previous_timeline"),
            audio_dna=context.get("audio_dna", {}),
            error_prompt=context.get("error_prompt", ""),
            # 糾錯模式：上一輪被 Critic 打回時 ReflectionState 會塞入待修正草稿，供就地最小修正
            draft_to_fix=context.get("draft_to_fix"),
        )

        # 呼叫後端：把 schema 交給後端結構化輸出（Gemini response_schema / Claude structured
        # outputs）保證結構合法，與 provider 無關
        raw_response = manager.generate_director_plan(prompt=spec.text, schema=spec.schema)
        
        # 【修改點 1】呼叫新的解析器
        parsed_data = self._parse_json_response(raw_response)
        
        # 【修改點 2】根據新版格式分別取出 timeline / bgm_track / text_overlays（字幕軌）
        if isinstance(parsed_data, dict) and "timeline" in parsed_data:
            context["timeline_draft"] = parsed_data.get("timeline", [])
            context["bgm_track"] = parsed_data.get("bgm_track", {"track_id": None})
            # 字幕為與 timeline 平行的頂層陣列：須在此一併接出存進 context，
            # 否則 DirectorFacade 重組 final_blueprint 時會遺失（藍圖是重建、非原樣帶過）。
            context["text_overlays"] = parsed_data.get("text_overlays", [])
        elif isinstance(parsed_data, list):
            # 容錯：如果 LLM 退化輸出純陣列
            context["timeline_draft"] = parsed_data
            context["bgm_track"] = {"track_id": None}
            context["text_overlays"] = []
        else:
            context["timeline_draft"] = []
            context["bgm_track"] = {"track_id": None}
            context["text_overlays"] = []
        
        from director_agent.states.reflection_state import ReflectionState
        return ReflectionState()

    def _parse_json_response(self, text: str):
        """
        解析導演藍圖 JSON：委派共用容錯解析器 :func:`parse_json_lenient`（DRY）。

        tool use / response_schema 路徑下 ``text`` 恆為合法 JSON、第一層即命中；僅 Claude 未走
        tool use 的自由文字退路才需後續分層（去圍欄 / 擷取 / json-repair）兜底，避免單一漏逗號
        讓整份草稿報廢（→ 空草稿 → ReflectionState 整輪重生）。失敗時保留原本的索引式除錯日誌。
        """
        result = parse_json_lenient(text, default={})
        if not result:
            print(f"[JSON Parse Error] 草稿解析失敗（已嘗試容錯）；文字前 120 字：{text[:120]!r}")
        return result