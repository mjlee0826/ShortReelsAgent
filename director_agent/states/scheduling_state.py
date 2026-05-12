import json
import re
from director_agent.states.base_state import BaseState
from model.gemini_model_manager import GeminiModelManager
from prompt_manager.prompt_factory import PromptFactory
from prompt_manager.task_mode import TaskMode

class SchedulingState(BaseState):
    
    def run(self, context: dict):
        print("\n[Agent State] 正在呼叫高強度導演模型生成藍圖...")
        
        gemini = GeminiModelManager()
        
        # 透過 PromptFactory 請求 Prompt
        full_prompt = PromptFactory.create_prompt(
            mode=TaskMode.DIRECTOR_SCHEDULING,
            manager=gemini.prompt_manager,
            user_prompt=context.get("user_prompt", ""),
            assets=context.get("assets", []),
            template_dna=context.get("template_dna"),        
            previous_timeline=context.get("previous_timeline"), 
            audio_dna=context.get("audio_dna", {}),
            error_prompt=context.get("error_prompt", "")
        )

        # 呼叫後端
        raw_response = gemini.generate_director_plan(prompt=full_prompt)
        
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

    # 【修改點 3】升級正則表達式，優先抓取大括號 {} Object
    def _parse_json_response(self, text: str):
        """強健的 JSON 解析器 (支援 Object 與 Array)"""
        try:
            # 先嘗試抓取 JSON Object
            match_obj = re.search(r'\{.*\}', text, re.DOTALL)
            if match_obj:
                return json.loads(match_obj.group(0))
            
            # 若抓不到，退回嘗試抓取 JSON Array
            match_arr = re.search(r'\[.*\]', text, re.DOTALL)
            if match_arr:
                return json.loads(match_arr.group(0))
                
            return {}
        except Exception as e:
            print(f"[JSON Parse Error] 草稿解析失敗: {e}")
            return {}