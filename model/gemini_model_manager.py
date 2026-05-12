import os
import re
import json
import time
# 【重構】使用全新官方支援的 google.genai SDK
from google import genai
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode
from prompt_manager.prompt_factory import PromptFactory
from model.base_model_manager import BaseModelManager

class GeminiModelManager(BaseModelManager):
    """統一的雲端大腦 (Gemini)。已遷移至最新 google.genai 架構。"""

    def _initialize(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("嚴重錯誤：找不到 GEMINI_API_KEY 環境變數！請設定後再執行。")

        # 【重構】使用新版 Client 實例化寫法
        self.client = genai.Client(api_key=api_key)
        self.default_model = 'gemini-2.5-flash'
        self.strong_model = 'gemini-3.1-pro-preview'
        self.prompt_manager = DefaultPromptManager()

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        self.prompt_manager = prompt_manager

    def analyze_media(self, media_input: str, media_type="video", mode: TaskMode = TaskMode.TIMECODED_ACTION_INDEX) -> dict:
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)
        video_file = None

        try:
            print(f"[Gemini API] 正在上傳影片至雲端: {media_input}")
            # 【重構】新版檔案上傳 API
            video_file = self.client.files.upload(file=media_input)

            # 輪詢等待 Gemini 後台處理影片完成 (最多 5 分鐘)
            poll_count = 0
            while video_file.state.name == 'PROCESSING':
                if poll_count >= 150:
                    raise TimeoutError("Gemini 影片處理逾時（超過 5 分鐘），請稍後重試或換短影片。")
                poll_count += 1
                print("[Gemini API] 影片處理中，等待 2 秒...")
                time.sleep(2)
                video_file = self.client.files.get(name=video_file.name)

            if video_file.state.name == 'FAILED':
                raise ValueError("Gemini 影片處理失敗。")

            print("[Gemini API] 開始進行語意與時間碼推論...")
            # 【重構】新版生成內容 API (注意 contents 陣列的傳遞方式)
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
                except:
                    pass

    def generate_director_plan(self, prompt: str, tools: list = None) -> str:
        """
        Agentic 核心：建立對話 Session 並處理 Tool Calling 迴圈。
        """
        # 建立具備工具能力的 Chat Session
        # config 中註冊 tools (例如 Phase 3 的 MusicEngineFacade 方法)
        chat = self.client.chats.create(
            model=self.strong_model,
            config={'tools': tools} if tools else None
        )

        response = chat.send_message(prompt)

        # 進入 Agentic Loop: 處理模型產生的所有工具呼叫請求
        # 備註：google.genai SDK 會自動處理簡單的 Function Call 對接，
        # 但在複雜邏輯下我們可以在此攔截並執行本地邏輯。
        
        return response.text

    def _parse_json_output(self, text: str) -> dict:
        """強健的 JSON 解析器"""
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {"multimodal_event_index": []}
        except Exception as e:
            print(f"[JSON Parse Error] 解析失敗: {e}")
            return {"multimodal_event_index": []}