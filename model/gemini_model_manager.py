import os
import time
from google import genai
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode
from prompt_manager.prompt_factory import PromptFactory
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    GEMINI_DEFAULT_MODEL,
    GEMINI_STRONG_MODEL,
    GEMINI_POLL_MAX_COUNT,
    GEMINI_POLL_INTERVAL_SEC,
)


class GeminiModelManager(BaseModelManager):
    """統一的雲端大腦 (Gemini)。已遷移至最新 google.genai 架構。"""

    def _initialize(self, device_id: int = 0):
        """初始化 Gemini Client。device_id 對雲端 API 無效，保留簽名一致性。"""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("嚴重錯誤：找不到 GEMINI_API_KEY 環境變數！請設定後再執行。")

        self.client = genai.Client(api_key=api_key)
        self.default_model = GEMINI_DEFAULT_MODEL
        self.strong_model = GEMINI_STRONG_MODEL
        self.prompt_manager = DefaultPromptManager()

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        """替換 Prompt Manager（Strategy Pattern）。"""
        self.prompt_manager = prompt_manager

    @synchronized_inference
    def analyze_media(self, media_input: str, media_type: str = "video", mode: TaskMode = TaskMode.TIMECODED_ACTION_INDEX) -> dict:
        """上傳媒體至 Gemini 並取得語意推論結果。"""
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)
        video_file = None

        try:
            print(f"[Gemini API] 正在上傳影片至雲端: {media_input}")
            video_file = self.client.files.upload(file=media_input)

            # 輪詢等待 Gemini 後台處理影片完成
            poll_count = 0
            while video_file.state.name == 'PROCESSING':
                if poll_count >= GEMINI_POLL_MAX_COUNT:
                    raise TimeoutError("Gemini 影片處理逾時（超過 5 分鐘），請稍後重試或換短影片。")
                poll_count += 1
                print("[Gemini API] 影片處理中，等待 2 秒...")
                time.sleep(GEMINI_POLL_INTERVAL_SEC)
                video_file = self.client.files.get(name=video_file.name)

            if video_file.state.name == 'FAILED':
                raise ValueError("Gemini 影片處理失敗。")

            print("[Gemini API] 開始進行語意與時間碼推論...")
            response = self.client.models.generate_content(
                model=self.default_model,
                contents=[video_file, prompt_text]
            )
            return self._parse_json_output(response.text)

        except Exception as e:
            print(f"[Gemini API Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "caption": "Unknown action", "multimodal_event_index": []}
        finally:
            # 確保上傳的檔案會被刪除，保護隱私與配額
            if video_file:
                try:
                    self.client.files.delete(name=video_file.name)
                    print(f"[Gemini API] 已清理雲端暫存檔: {video_file.name}")
                except Exception as e:
                    print(f"[Gemini API] 無法刪除雲端暫存檔: {e}")

    @synchronized_inference
    def generate_director_plan(self, prompt: str, tools: list = None) -> str:
        """Agentic 核心：建立對話 Session 並傳送指令。"""
        chat = self.client.chats.create(
            model=self.strong_model,
            config={'tools': tools} if tools else None
        )
        response = chat.send_message(prompt)
        return response.text
