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
            "你現在是精密的影片內容紀錄員。\n"
            "這是一段 3到4 秒的短影片切片，請用一句話簡潔、客觀地描述這段時間內的畫面內容、動態變化、主要內容與動作。\n\n"
            "【觀察重點】\n"
            "1. 畫面中有什麼：主體是誰？。\n"
            "2. 發生了什麼變化：主體做了什麼動作？或是鏡頭有什麼移動？。\n"
            "3. 畫面描述請具備時序感，描述這 4 秒內的起點與終點狀態變化。\n"
            "4. 如果變化不多，則需要詳細描述變化的部分。\n"
            "5. 主觀評價這段素材的『鏡頭語言』與『情緒氛圍』\n\n"
            "【嚴格格式要求】直接輸出 JSON，不要包含 markdown 標記，不要有任何多餘的解釋或占位符。\n"
            "{\n"
            "  \"caption\": \"在此輸入你的客觀觀察描述\"\n"
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