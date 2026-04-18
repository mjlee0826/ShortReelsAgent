from PromptManager.BasePromptManager import BasePromptManager

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    重構：移除座標計算與模糊判斷，回歸最純粹的視覺語意描述，大幅提升 Qwen 的推論速度。
    """
    
    def get_media_analysis_prompt(self) -> str:
        return (
            "請詳細描述這份素材(圖片或影片)的主要內容與動作。"
            "請以嚴格的 JSON 格式回傳，絕對不能包含其他 markdown 標記，必須只包含一個 key: "
            "'caption' (字串，繁體中文描述)。"
        )