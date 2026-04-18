from PromptManager.BasePromptManager import BasePromptManager

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    針對不同任務提供專門的指令，並嚴格限制 JSON 格式輸出。
    """
    
    def get_media_analysis_prompt(self) -> str:
        return (
            "請扮演一位專業的電影攝影指導 (DP)。\n"
            "1. 請先客觀地詳細描述這份素材(圖片或影片)的主要內容與動作。\n"
            "2. 接著，請主觀評價這段素材的『鏡頭語言』與『情緒氛圍』(例如：光影、色調、構圖等)。\n"
            "【嚴格格式要求】直接輸出 JSON，不要包含 markdown 標記。\n"
            "{\n"
            "  \"caption\": \"客觀描述\",\n"
            "  \"cinematic_critique\": \"攝影評論\"\n"
            "}"
        )

    def get_action_index_prompt(self) -> str:
        return (
            "你現在是動作捕捉分析師。\n"
            "這是一段 2 到 3 秒的短影片切片，請精確描述這段時間內發生的『關鍵物理動作』。\n"
            "不需要分析美學，只要告訴我人物或物體做了什麼（例如：轉身跳躍、向鏡頭招手、車輛快速駛過）。\n"
            "【嚴格格式要求】直接輸出 JSON，不要包含 markdown 標記。\n"
            "{\n"
            "  \"action_description\": \"具體的動作描述\"\n"
            "}"
        )

    def get_cinematic_style_prompt(self) -> str:
        return (
            "你現在是資深視覺導演。正在進行影片逆向工程。\n"
            "請分析這個分鏡的視覺 DNA。包含：\n"
            "1. 運鏡方式 (如：Dolly In, Pan, Tilt, 或手持震動感)\n"
            "2. 景別 (特寫、中景、遠景)\n"
            "3. 核心標籤 (如：高對比、日系清新、賽博龐克、低對比度)\n"
            "【嚴格格式要求】直接輸出 JSON，不要包含 markdown 標記。\n"
            "{\n"
            "  \"camera_movement\": \"運鏡描述\",\n"
            "  \"shot_type\": \"景別名稱\",\n"
            "  \"visual_style\": [\"標籤1\", \"標籤2\"]\n"
            "}"
        )