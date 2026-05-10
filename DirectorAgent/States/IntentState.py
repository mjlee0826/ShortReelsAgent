import json
import re
from DirectorAgent.States.BaseState import BaseState
from Model.GeminiModelManager import GeminiModelManager
from MusicEngine.MusicEngineFacade import MusicEngineFacade
from PromptManager.PromptFactory import PromptFactory
from PromptManager.TaskMode import TaskMode


class IntentState(BaseState):
    """
    State Pattern：Phase 3 音樂路由決策節點。
    根據前端傳入的 music_strategy 決定配樂來源，不再依賴 Gemini 做路由判斷。
    Gemini 僅負責從 user_prompt 萃取搜尋關鍵字。

    路由優先級（高→低）：
      1. user_music_file 存在 → 直接使用本地上傳檔案
      2. music_strategy == "none"   → 跳過 Phase 3，不加配樂
      3. music_strategy == "search_copyright" → yt-dlp 搜尋（可能含版權）
      4. music_strategy == "search_free"      → JamendoAdapter（無版權）
    """

    def run(self, context: dict):
        print("\n[Agent State] 進入 IntentState：決定配樂策略...")

        music_engine = MusicEngineFacade()
        user_music_file = context.get("user_music_file")
        music_strategy = context.get("music_strategy", "search_copyright")

        # 最高優先：用戶已上傳自訂音樂，直接使用本地檔案，跳過所有搜尋邏輯
        if user_music_file:
            print(f"[Agent State] ⏩ 策略: 使用本地上傳音訊 ({user_music_file})")
            context["audio_dna"] = music_engine.use_local_audio(user_music_file)
            return self._next_state()

        # 不加配樂：直接跳過，無需呼叫 Gemini
        if music_strategy == "none":
            print("[Agent State] ⏩ 策略: 不加配樂，跳過 Phase 3。")
            context["audio_dna"] = {}
            return self._next_state()

        # 搜尋配樂：先請 Gemini 萃取關鍵字，再依策略選擇下載來源
        search_query = self._extract_search_query(context)

        if music_strategy == "search_copyright":
            print(f"[Agent State] 🎵 策略: 搜尋配樂（含版權），關鍵字: '{search_query}'")
            context["audio_dna"] = self._safe_fetch_music(music_engine, search_query)

        elif music_strategy == "search_free":
            print(f"[Agent State] 🆓 策略: 搜尋免費配樂 (Jamendo)，關鍵字: '{search_query}'")
            context["audio_dna"] = self._safe_fetch_free_music(music_engine, search_query)

        else:
            # 未知策略：fallback 至 search_copyright，避免靜默失敗
            print(f"⚠️ [Agent State] 未知策略 '{music_strategy}'，fallback 至 search_copyright")
            context["audio_dna"] = self._safe_fetch_music(music_engine, search_query)

        return self._next_state()

    def _extract_search_query(self, context: dict) -> str:
        """
        呼叫 Gemini 從 user_prompt 萃取音樂搜尋關鍵字。
        Gemini 僅做關鍵字萃取，路由決策已由 music_strategy 控制。
        失敗時退回原始 user_prompt 作為搜尋詞。
        """
        user_prompt = context.get("user_prompt", "")
        gemini = GeminiModelManager()

        analysis_prompt = PromptFactory.create_prompt(
            mode=TaskMode.INTENT_TRANSLATION,
            manager=gemini.prompt_manager,
            user_prompt=user_prompt
        )

        try:
            response = gemini.client.models.generate_content(
                model=gemini.default_model,
                contents=analysis_prompt
            )
            match = re.search(r'\{.*\}', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                query = data.get("search_query", "").strip()
                if query:
                    print(f"[Agent State] Gemini 萃取搜尋關鍵字: '{query}'")
                    return query
        except Exception as e:
            print(f"⚠️ [Intent 解析錯誤] 將使用原始 Prompt 作為搜尋詞。原因: {e}")

        return user_prompt

    def _safe_fetch_music(self, music_engine: MusicEngineFacade, query: str) -> dict:
        """呼叫 yt-dlp 搜尋並下載配樂（情境1：含版權）。失敗時回傳空 dict。"""
        result = music_engine.fetch_and_analyze(query=query)
        if result.get("status") != "success":
            print(f"⚠️ [MusicEngine] 配樂獲取失敗: {result.get('message', '未知錯誤')}，將使用空配樂繼續。")
            return {}
        return result

    def _safe_fetch_free_music(self, music_engine: MusicEngineFacade, query: str) -> dict:
        """呼叫 Jamendo 搜尋免費配樂（情境3）。失敗時回傳空 dict。"""
        result = music_engine.fetch_free_music(query=query)
        if result.get("status") != "success":
            print(f"⚠️ [MusicEngine] 免費配樂獲取失敗: {result.get('message', '未知錯誤')}，將使用空配樂繼續。")
            return {}
        return result

    def _next_state(self):
        """統一的狀態切換出口，轉至排程階段。"""
        from DirectorAgent.States.SchedulingState import SchedulingState
        return SchedulingState()
