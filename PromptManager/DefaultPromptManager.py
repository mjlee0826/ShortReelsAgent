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

    def get_timecoded_action_index_prompt(self) -> str:
        return (
            "你現在是專業的『AI 影片剪輯大腦』與視聽分析師。\n"
            "這支影片的左上角已經印上了『精確的秒數時間碼 (例如 12.345)』。\n\n"
            "【你的任務】\n"
            "1. 請全局觀看並『聆聽』這支影片，理解敘事的起承轉合與聲音情緒。\n"
            "2. 請根據左上角的實際秒數，將影片拆解為數個『連續的多模態事件區塊』。\n"
            "3. 每個區塊必須包含『視覺層 (visual_layer)』與『聽覺層 (audio_layer)』的描述。\n"
            "4. 聽覺層請記錄人說的話、人聲情緒、環境音，或配樂的起伏節奏。\n"
            "5. 在每個區塊中，請挑出一個『最關鍵的時間點 (key_timestamp)』。如果該區段有強烈的聲音爆發(如笑聲、碎裂聲)或動作高潮，請填入該精確秒數。\n"
            "6. 同時給出整支影片的『全局攝影評論』。\n\n"
            "【嚴格格式要求】請直接輸出 JSON，不要包含 markdown 標記。時間請使用小數 (float)。\n"
            "{\n"
            "  \"cinematic_critique\": \"整支影片的運鏡與情緒氛圍評論\",\n"
            "  \"multimodal_event_index\": [\n"
            "    {\n"
            "      \"start_time\": 0.0,\n"
            "      \"end_time\": 4.5,\n"
            "      \"visual_layer\": \"人物連續旋轉舞步，動作流暢\",\n"
            "      \"audio_layer\": \"背景音樂節奏加快，03.2秒處有明顯的重拍與歡呼聲\",\n"
            "      \"key_timestamp\": 3.2\n"
            "    }\n"
            "  ]\n"
            "}"
        )