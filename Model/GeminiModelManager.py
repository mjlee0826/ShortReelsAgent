import os
import re
import json
import time
import google.generativeai as genai
from PromptManager.BasePromptManager import BasePromptManager
from PromptManager.DefaultPromptManager import DefaultPromptManager
from PromptManager.TaskMode import TaskMode
from PromptManager.PromptFactory import PromptFactory

class GeminiModelManager:
    """
    單例模式 (Singleton): 統一的雲端大腦 (Gemini 1.5 Flash)。
    使用 File API 上傳影片，支援超長上下文與精準 OCR。
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
        
        genai.configure(api_key=api_key)
        # 採用極具性價比且速度快的 flash 版本
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        self.prompt_manager = prompt_manager if prompt_manager else DefaultPromptManager()

    def analyze_media(self, media_input: str, media_type="video", mode: TaskMode = TaskMode.TIMECODED_ACTION_INDEX) -> dict:
        prompt_text = PromptFactory.create_prompt(mode, self.prompt_manager)
        video_file = None

        try:
            print(f"[Gemini API] 正在上傳影片至雲端: {media_input}")
            video_file = genai.upload_file(path=media_input)

            # 輪詢等待 Gemini 後台處理影片完成
            while video_file.state.name == 'PROCESSING':
                print("[Gemini API] 影片處理中，等待 2 秒...")
                time.sleep(2)
                video_file = genai.get_file(video_file.name)

            if video_file.state.name == 'FAILED':
                raise ValueError("Gemini 影片處理失敗。")

            print("[Gemini API] 開始進行語意與時間碼推論...")
            response = self.model.generate_content([prompt_text, video_file])
            return self._parse_json_output(response.text)

        except Exception as e:
            print(f"[Gemini API Error] 推理失敗: {str(e)}")
            return {"error": "Analysis failed", "caption": "Unknown action", "action_index": []}
        finally:
            # 確保上傳的檔案會被刪除，保護隱私與配額
            if video_file:
                try:
                    genai.delete_file(video_file.name)
                    print(f"[Gemini API] 已清理雲端暫存檔: {video_file.name}")
                except:
                    pass

    def _parse_json_output(self, text: str) -> dict:
        """強健的 JSON 解析器"""
        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {"action_index": []}
        except Exception as e:
            print(f"[JSON Parse Error] 解析失敗: {e}")
            return {"action_index": []}