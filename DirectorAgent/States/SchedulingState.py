import json
import re
from DirectorAgent.States.BaseState import BaseState
from Model.GeminiModelManager import GeminiModelManager
from PromptManager.PromptFactory import PromptFactory
from PromptManager.TaskMode import TaskMode

class SchedulingState(BaseState):
    
    def run(self, context: dict):
        print("\n[Agent State] 正在呼叫高強度導演模型生成藍圖...")
        
        gemini = GeminiModelManager()
        
        # 透過 PromptFactory 請求 Prompt，並傳入 template 與 previous_timeline
        full_prompt = PromptFactory.create_prompt(
            mode=TaskMode.DIRECTOR_SCHEDULING,
            manager=gemini.prompt_manager,
            user_prompt=context.get("user_prompt", ""),
            assets=context.get("assets", []),
            template_dna=context.get("template_dna"),        # 傳入範本
            previous_timeline=context.get("previous_timeline"), # 傳入舊稿
            audio_dna=context.get("audio_dna", {}),
            error_prompt=context.get("error_prompt", "")
        )

        # 呼叫後端 (自動切換至強模型 gemini-3.1-pro-preview)
        raw_response = gemini.generate_director_plan(prompt=full_prompt)
        
        context["timeline_draft"] = self._parse_json_array(raw_response)
        
        from DirectorAgent.States.ReflectionState import ReflectionState
        return ReflectionState()

    def _parse_json_array(self, text: str) -> list:
        """強健的 JSON Array 解析器"""
        try:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return []
        except Exception as e:
            print(f"[JSON Parse Error] 草稿解析失敗: {e}")
            return []