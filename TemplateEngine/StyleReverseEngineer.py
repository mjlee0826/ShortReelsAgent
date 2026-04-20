from Model.GeminiModelManager import GeminiModelManager
from PromptManager.TaskMode import TaskMode

class StyleReverseEngineer:
    """
    語意逆向模組：利用 Gemini 2.5 Flash 提取範本的視覺 DNA 與聲音重要性。
    """
    def __init__(self):
        # 複用 Phase 1 建立好的單例大腦
        self.engine = GeminiModelManager()

    def reverse_style(self, video_path: str) -> dict:
        print(f"[Gemini] 正在進行範本語意逆向工程...")
        
        # 使用 STYLE_EXTRACTION 模式 (Phase 2 專用)
        result = self.engine.analyze_media(
            media_input=video_path,
            media_type="video",
            mode=TaskMode.STYLE_EXTRACTION
        )
        
        # 我們額外要求模型判斷聲音是否有不可取代的價值
        # 這部分會由 PromptManager 的內容決定回傳 JSON 內容
        return result