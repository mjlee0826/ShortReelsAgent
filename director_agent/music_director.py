import json
import re

from model.managers.gemini_model_manager import GeminiModelManager
from music_engine.music_engine_facade import MusicEngineFacade
from media_processor.pipeline.progress import ProgressTracker
from prompt_manager.prompt_factory import PromptFactory
from prompt_manager.task_mode import TaskMode

# 配樂策略常數（取代散落的字串，禁 magic string）
MUSIC_STRATEGY_NONE = "none"
MUSIC_STRATEGY_SEARCH_COPYRIGHT = "search_copyright"
MUSIC_STRATEGY_SEARCH_FREE = "search_free"


class MusicDirector:
    """
    Phase 3 配樂決策（與狀態機解耦的獨立模組）。

    職責單一：給定「配樂意圖」(策略 / 上傳檔 / 關鍵字 prompt)，解析出 ``audio_dna``。
    供兩處重用且邏輯完全一致：
      - 生成流程的 ``MusicDnaProducer``（fork-join 分支生產者，與 template 分支並行）
      - 「只換音樂」的 ``DirectorService.change_music``（不重剪時間軸）

    路由優先級（高→低）：
      1. user_music_file 存在 → 直接使用本地上傳檔案
      2. music_strategy == "none"            → 不加配樂（回空 dict）
      3. music_strategy == "search_copyright" → yt-dlp 搜尋（可能含版權）
      4. music_strategy == "search_free"      → JamendoAdapter（無版權）
    Gemini 僅負責從 user_prompt 萃取搜尋關鍵字，不做路由判斷。
    """

    def __init__(self):
        """初始化配樂引擎 Facade（yt-dlp / Jamendo / 本地音訊的低階存取）。"""
        self.music_engine = MusicEngineFacade()

    def resolve(self, music_strategy: str = MUSIC_STRATEGY_SEARCH_COPYRIGHT,
                user_music_file: str = None, user_prompt: str = "",
                tracker: ProgressTracker | None = None) -> dict:
        """
        依配樂意圖解析出 audio_dna；無配樂 / 取得失敗一律回空 dict（呼叫端據此視為「無配樂」）。
        :param music_strategy: 配樂策略 (search_copyright | search_free | none)
        :param user_music_file: 用戶上傳的本地音訊絕對路徑（有值時最優先）
        :param user_prompt: 供 Gemini 萃取搜尋關鍵字的指令 / 風格描述
        :param tracker: (選填) 進度 tracker;非 None 時把下載 / 節拍 / 聽寫 STAGE_* 帶上前端
        """
        # 最高優先：用戶已上傳自訂音樂，直接使用本地檔案，跳過所有搜尋邏輯
        if user_music_file:
            print(f"[MusicDirector] ⏩ 使用本地上傳音訊 ({user_music_file})")
            return self.music_engine.use_local_audio(user_music_file, tracker=tracker)

        # 不加配樂：直接返回，無需呼叫 Gemini
        if music_strategy == MUSIC_STRATEGY_NONE:
            print("[MusicDirector] ⏩ 策略: 不加配樂")
            return {}

        # 搜尋配樂：先請 Gemini 萃取關鍵字，再依策略選擇下載來源
        search_query = self._extract_search_query(user_prompt)

        if music_strategy == MUSIC_STRATEGY_SEARCH_FREE:
            print(f"[MusicDirector] 🆓 策略: 免費配樂 (Jamendo)，關鍵字: '{search_query}'")
            return self._safe_fetch_free_music(search_query, tracker=tracker)

        if music_strategy != MUSIC_STRATEGY_SEARCH_COPYRIGHT:
            # 未知策略：fallback 至 search_copyright，避免靜默失敗
            print(f"⚠️ [MusicDirector] 未知策略 '{music_strategy}'，fallback 至 search_copyright")
        else:
            print(f"[MusicDirector] 🎵 策略: 搜尋配樂（含版權），關鍵字: '{search_query}'")
        return self._safe_fetch_music(search_query, tracker=tracker)

    def _extract_search_query(self, user_prompt: str) -> str:
        """
        呼叫 Gemini 從 user_prompt 萃取音樂搜尋關鍵字（僅萃取、不做路由）。
        失敗時退回原始 user_prompt 作為搜尋詞。
        """
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
                    print(f"[MusicDirector] Gemini 萃取搜尋關鍵字: '{query}'")
                    return query
        except Exception as e:
            print(f"⚠️ [MusicDirector 解析錯誤] 將使用原始 Prompt 作為搜尋詞。原因: {e}")

        return user_prompt

    def _safe_fetch_music(self, query: str, tracker: ProgressTracker | None = None) -> dict:
        """呼叫 yt-dlp 搜尋並下載配樂（含版權）。失敗時回傳空 dict。"""
        result = self.music_engine.fetch_and_analyze(query=query, tracker=tracker)
        if result.get("status") != "success":
            print(f"⚠️ [music_engine] 配樂獲取失敗: {result.get('message', '未知錯誤')}，將使用空配樂繼續。")
            return {}
        return result

    def _safe_fetch_free_music(self, query: str, tracker: ProgressTracker | None = None) -> dict:
        """呼叫 Jamendo 搜尋免費配樂（無版權）。失敗時回傳空 dict。"""
        result = self.music_engine.fetch_free_music(query=query, tracker=tracker)
        if result.get("status") != "success":
            print(f"⚠️ [music_engine] 免費配樂獲取失敗: {result.get('message', '未知錯誤')}，將使用空配樂繼續。")
            return {}
        return result
