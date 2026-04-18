from PromptManager.BasePromptManager import BasePromptManager

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    重構：賦予模型「攝影指導」的 Persona，專心輸出客觀描述與主觀美學評語。
    """
    
    def get_media_analysis_prompt(self) -> str:
        return (
            "請扮演一位專業的電影攝影指導 (DP)。"
            "1. 請先客觀地詳細描述這份素材(圖片或影片)的主要內容與動作。\n"
            "2. 接著，請主觀評價這段素材的『鏡頭語言』與『情緒氛圍』(例如：光影、色調、構圖、手持呼吸感等)。\n"
            "請以嚴格的 JSON 格式回傳，絕對不能包含其他 markdown 標記，必須包含兩個 key: \n"
            "'caption' (字串，客觀的畫面內容描述), \n"
            "'cinematic_critique' (字串，主觀的攝影與美學評語)。"
        )