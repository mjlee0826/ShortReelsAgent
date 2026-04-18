from PromptManager.BasePromptManager import BasePromptManager

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    重構：加入 One-Shot 範例與更強硬的格式限制，強迫 Qwen 輸出純 JSON。
    """
    
    def get_media_analysis_prompt(self) -> str:
        return (
            "請扮演一位專業的電影攝影指導 (DP)。\n"
            "1. 請先客觀地詳細描述這份素材(圖片或影片)的主要內容與動作。\n"
            "2. 接著，請主觀評價這段素材的『鏡頭語言』與『情緒氛圍』(例如：光影、色調、構圖、手持呼吸感等)。\n"
            "【嚴格格式要求】\n"
            "請直接輸出 JSON，絕對不能包含任何 markdown 標記 (如 ```json)，也不要有任何開頭與結尾的問候語。\n"
            "你的輸出必須完全符合以下格式：\n"
            "{\n"
            "  \"caption\": \"客觀的畫面內容描述\",\n"
            "  \"cinematic_critique\": \"主觀的攝影與美學評語\"\n"
            "}"
        )