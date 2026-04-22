from DirectorAgent.States.BaseState import BaseState
from Model.GeminiModelManager import GeminiModelManager
from MusicEngine.MusicEngineFacade import MusicEngineFacade

class IntentState(BaseState):
    """
    狀態：分析意圖並執行 Phase 3 工具呼叫。
    """
    def run(self, context: dict):
        print("[Agent State] 正在分析使用者意圖與配置音樂...")
        gemini = GeminiModelManager()
        music_engine = MusicEngineFacade()
        
        # 註冊 Phase 3 作為工具
        tools = [music_engine.fetch_and_analyze]
        
        user_prompt = context["user_prompt"]
        # 這裡的邏輯是啟動一個會話，讓 Gemini 決定是否要呼叫音樂搜尋
        # 暫時簡化為：如果 Prompt 提到音樂，就手動或由 LLM 自動呼叫
        # 最終會將 audio_dna 存入 context
        context["audio_dna"] = music_engine.fetch_and_analyze(user_prompt)
        
        # 切換到下一狀態
        from DirectorAgent.States.SchedulingState import SchedulingState
        return SchedulingState()