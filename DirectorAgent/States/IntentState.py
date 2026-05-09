import json
import re
from DirectorAgent.States.BaseState import BaseState
from Model.GeminiModelManager import GeminiModelManager
from MusicEngine.MusicEngineFacade import MusicEngineFacade
from PromptManager.PromptFactory import PromptFactory
from PromptManager.TaskMode import TaskMode

class IntentState(BaseState):
    """
    狀態：分析意圖並決定音樂獲取策略 (Action Routing)。
    """
    def run(self, context: dict):
        print("\n[Agent State] 進入 IntentState：正在分析使用者意圖與配置音樂...")
        
        gemini = GeminiModelManager()
        music_engine = MusicEngineFacade()
        user_prompt = context.get("user_prompt", "")
        template_dna = context.get("template_dna") # 把範本拿出來備用

        print("[Agent State] 正在請 Gemini 決定配樂策略...")
        
        analysis_prompt = PromptFactory.create_prompt(
            mode=TaskMode.INTENT_TRANSLATION,
            manager=gemini.prompt_manager,
            user_prompt=user_prompt
        )

        # 預設行為
        music_action = "search"
        search_query = user_prompt

        try:
            response = gemini.client.models.generate_content(
                model=gemini.default_model,
                contents=analysis_prompt
            )
            
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                music_action = data.get("music_action", "search")
                search_query = data.get("search_query", user_prompt)
                
        except Exception as e:
            print(f"⚠️ [Intent 解析錯誤] 將使用預設 Search 策略。原因: {str(e)}")

        print(f"🎵 [Agent State] AI 決定的音樂策略為: '{music_action}'")

        # ---------------------------------------------------------
        # 核心升級：分情況處理 (Action Routing)
        # ---------------------------------------------------------
        if music_action == "none":
            print("[Agent State] ⏩ 策略: 無配樂，跳過 Phase 3 搜尋。")
            context["audio_dna"] = {}

        elif music_action == "use_template":
            if template_dna and "audio_beats" in template_dna:
                print("[Agent State] ⏩ 策略: 繼承範本配樂，跳過 Phase 3 搜尋。")

                template_audio_path = template_dna.get("local_assets", {}).get("audio_only", "")
                context["audio_dna"] = {
                    "source": "template",
                    "local_path": {"standard": template_audio_path},
                    "analysis": template_dna.get("audio_beats", {})
                }
            else:
                print("⚠️ [Agent State] 找不到有效的範本音樂，強制退回搜尋策略！")
                context["audio_dna"] = self._safe_fetch_music(music_engine, search_query)

        else:  # 預設就是 "search"
            print(f"[Agent State] 🔍 策略: 全網檢索，關鍵字為 '{search_query}'")
            context["audio_dna"] = self._safe_fetch_music(music_engine, search_query)
        
        # ---------------------------------------------------------
        # 切換到排程狀態
        # ---------------------------------------------------------
        from DirectorAgent.States.SchedulingState import SchedulingState
        return SchedulingState()

    def _safe_fetch_music(self, music_engine, query: str) -> dict:
        """包裝 fetch_and_analyze，確保失敗時不會把 error dict 傳給 LLM。"""
        result = music_engine.fetch_and_analyze(query=query)
        if result.get("status") != "success":
            print(f"⚠️ [MusicEngine] 音樂獲取失敗: {result.get('message', '未知錯誤')}，將使用空配樂繼續。")
            return {}
        return result