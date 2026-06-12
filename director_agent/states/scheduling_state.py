import json
import re
from director_agent.states.base_state import BaseState
from model.managers.gemini_model_manager import GeminiModelManager
from prompt_manager.prompt_factory import PromptFactory
from prompt_manager.task_mode import TaskMode

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
        
        gemini = GeminiModelManager()
        
        # 透過 PromptFactory 請求 PromptSpec(文字 + 結構化輸出 schema)
        spec = PromptFactory.create_prompt(
            mode=TaskMode.DIRECTOR_BLUEPRINT,
            manager=gemini.prompt_manager,
            user_prompt=context.get("user_prompt", ""),
            assets=assets,
            template_dna=context.get("template_dna"),
            previous_timeline=context.get("previous_timeline"),
            audio_dna=context.get("audio_dna", {}),
            error_prompt=context.get("error_prompt", ""),
        )

        # 呼叫後端：把 schema 交給 response_schema，由 Gemini 保證輸出結構合法
        raw_response = gemini.generate_director_plan(prompt=spec.text, schema=spec.schema)
        
        # 【修改點 1】呼叫新的解析器
        parsed_data = self._parse_json_response(raw_response)
        
        # 【修改點 2】根據新版格式分別取出 timeline 與 bgm_track
        if isinstance(parsed_data, dict) and "timeline" in parsed_data:
            context["timeline_draft"] = parsed_data.get("timeline", [])
            context["bgm_track"] = parsed_data.get("bgm_track", {"track_id": None})
        elif isinstance(parsed_data, list):
            # 容錯：如果 LLM 退化輸出純陣列
            context["timeline_draft"] = parsed_data
            context["bgm_track"] = {"track_id": None}
        else:
            context["timeline_draft"] = []
            context["bgm_track"] = {"track_id": None}
        
        from director_agent.states.reflection_state import ReflectionState
        return ReflectionState()

    def _parse_json_response(self, text: str):
        """
        解析導演藍圖 JSON。

        response_schema 已保證輸出為合法 JSON object(DirectorBlueprint 結構)，故優先直接
        ``json.loads``；僅在極端情況(schema 未生效 / 被 markdown 包裹)才退回寬鬆的大括號抓取，
        維持容錯不致整批失敗。
        """
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        # fallback：schema 未生效時，寬鬆抓取第一個 JSON object
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f"[JSON Parse Error] 草稿解析失敗: {e}")
        return {}