import os
import re
import json
import time
# 【重構】使用全新官方支援的 google.genai SDK
from google import genai
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager
from PromptManager.TaskMode import TaskMode
from PromptManager.PromptFactory import PromptFactory

class GeminiModelManager:
    """
    單例模式 (Singleton): 統一的雲端大腦 (Gemini 1.5 Flash)。
    【修復】已遷移至最新 google.genai 架構，解決棄用警告。
    """
    _instance = None

    def __new__(cls, prompt_manager: BasePromptManager = None):
        if cls._instance is None:
            cls._instance = super(GeminiModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize(prompt_manager)
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self, prompt_manager: BasePromptManager):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("嚴重錯誤：找不到 GEMINI_API_KEY 環境變數！請設定後再執行。")
        
        # 【重構】使用新版 Client 實例化寫法
        self.client = genai.Client(api_key=api_key)
        self.model_id = 'gemini-2.5-flash'
        self.prompt_manager = prompt_manager if prompt_manager else DefaultPromptManager()

    def analyze_media(self, media_input: str, media_type="video", mode: TaskMode = TaskMode.TIMECODED_ACTION_INDEX) -> dict:
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)
        video_file = None

        try:
            print(f"[Gemini API] 正在上傳影片至雲端: {media_input}")
            # 【重構】新版檔案上傳 API
            video_file = self.client.files.upload(file=media_input)

            # 輪詢等待 Gemini 後台處理影片完成
            while video_file.state.name == 'PROCESSING':
                print("[Gemini API] 影片處理中，等待 2 秒...")
                time.sleep(2)
                video_file = self.client.files.get(name=video_file.name)

            if video_file.state.name == 'FAILED':
                raise ValueError("Gemini 影片處理失敗。")

            print("[Gemini API] 開始進行語意與時間碼推論...")
            # 【重構】新版生成內容 API (注意 contents 陣列的傳遞方式)
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=[video_file, prompt_text]
            )
            return self._parse_json_output(response.text)

        except Exception as e:
            print(f"[Gemini API Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "caption": "Unknown action", "action_index": []}
        finally:
            # 確保上傳的檔案會被刪除，保護隱私與配額
            if video_file:
                try:
                    self.client.files.delete(name=video_file.name)
                    print(f"[Gemini API] 已清理雲端暫存檔: {video_file.name}")
                except:
                    pass

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