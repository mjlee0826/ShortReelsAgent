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
    
    def get_timecoded_action_index_prompt(self) -> str:
        return (
            "你現在是專業的『AI 影片剪輯大腦』與視聽分析師。\n"
            "這支影片的畫面上方或左上角已經印上了『精確的秒數時間碼 (例如 12.345)』。\n\n"
            "【你的任務】\n"
            "1. 請全局觀看並『聆聽』這支影片，理解敘事的起承轉合與聲音情緒。\n"
            "2. 請根據實際秒數，將影片拆解為數個『連續的多模態事件區塊』。\n"
            "3. 每個區塊必須包含『視覺層 (visual_layer)』與『聽覺層 (audio_layer)』的描述。\n"
            "4. 聽覺層請記錄聲音氛圍（如人物逐字稿、人聲情緒、環境音、配樂起伏）。\n"
            "5. 在每個區塊中，請挑出一個『最關鍵的時間點 (key_timestamp)』。如果該區段有強烈的聲音爆發(如笑聲、碎裂聲)或動作高潮，請填入該精確秒數。\n"
            "6. 逐字稿聽寫：請精準聽寫出影片中所有的人聲對白，並根據畫面上印製的時間碼，精確標註每一句話的開始與結束時間。\n"
            "7. 同時給出整支影片的『全局攝影評論』。\n\n"
            "【嚴格格式要求】請直接輸出 JSON，不要包含 markdown 標記。時間請使用小數 (float)。若影片無人聲對白，audio_transcript 內的 text 請留空字串，chunks 請保持空陣列。\n"
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
            "  ],\n"
            "  \"audio_transcript\": {\n"
            "    \"text\": \"逐字稿1 逐字稿2\",\n"
            "    \"chunks\": [\n"
            "      {\n"
            "        \"timestamp\": [\n"
            "          0.0,\n"
            "          1.0\n"
            "        ],\n"
            "        \"text\": \"逐字稿1\"\n"
            "      },\n"
            "      {\n"
            "        \"timestamp\": [\n"
            "          4.0,\n"
            "          6.0\n"
            "        ],\n"
            "        \"text\": \"逐字稿2\"\n"
            "      }\n"
            "    ]\n"
            "  }\n"
            "}"
        )