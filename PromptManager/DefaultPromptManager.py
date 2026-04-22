from PromptManager.BasePromptManager import BasePromptManager
import json

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
    
    def get_director_prompt(self, user_prompt, assets, audio_dna, template_dna=None, previous_timeline=None, error_prompt=""):
        # 1. 定義角色與目標
        instruction = (
            "# ROLE\n"
            "你是一位頂尖的 AI 廣告導演與 Remotion 渲染架構師。\n"
            "你的任務是將手邊的素材與配樂，編排成一份完美的 JSON 剪輯藍圖，這份藍圖將直接送入 React/Remotion 引擎進行物理渲染。\n\n"
        )

        # 2. 最高指導原則 (User Intent)
        instruction += (
            "# CORE OBJECTIVE (最高指導原則)\n"
            "【絕對優先】：使用者的需求 (User Prompt) 凌駕於一切！\n"
            "無論音樂風格或素材原始氛圍為何，你都必須優先挑選最符合『使用者文字指令』的素材，並根據使用者的期望來定調影片節奏。\n\n"
        )

        # 3. 決策指引 (Decision Guidelines)
        instruction += (
            "# DECISION GUIDELINES (導演決策邏輯)\n"
            "請嚴格遵循以下邏輯進行排程：\n"
            "1. 素材挑選策略：(User Prompt 相關度) > (音樂情緒契合度) > (素材美學分數 aes)。只有在前兩者相近時，才挑選 aes 較高的畫面。\n"
            "2. 節奏與對齊 (Rhythm)：靜態圖片請依據 BPM 決定播放時長 (約 0.5s - 2.0s)。影片的高潮動作 (action_timestamps) 必須精準對齊音樂的重拍能量點 (onsets)。\n"
            "3. Remotion 空間裁切 (Cropping)：預設輸出平台為 **Instagram Reels / TikTok (9:16 直式 1080x1920)**。\n"
            "   - 若素材的 `res` (長寬比) 不是 9:16，Remotion 會強制將其放大並裁切 (`object-fit: cover`)。\n"
            "   - 你必須參考素材的 `focus` (主體重心 x, y 比例)，在 JSON 中輸出 `object_position` 屬性 (例如 '50% 30%')，確保重要主體不會被裁出畫面外。\n\n"
            "4. 嚴禁假剪輯 (No Fake Cuts)：相鄰的兩個片段，絕對不可以是同一個素材的「連續時間段」！如果上一個片段是 A 影片的 0~5秒，下一個片段絕對不能緊接著 A 影片的 5~10秒，這在視覺上等於沒有剪輯。請務必切換不同的素材，或至少跳躍到同一素材的不同時間點。"
            "5. 動態裁切 (Dynamic Cropping)：你必須確實讀取素材的 focus 數據來計算 object_position。嚴禁無腦全部填寫 '50% 50%'，否則會被視為嚴重失職。"
            "6. 嚴禁假剪輯與無意義碎切 (No Fake Cuts & Chopping)：\n"
            "   - 如果你要從同一支影片中擷取一段『連續的畫面』，請直接將其合併為【一個】長片段輸出。\n"
            "   - 絕對不要為了配合 Template 的多個切點，而把一段連續的畫面硬切成很多個小 JSON 物件！\n"
            "7. 嚴禁突兀跳剪 (No Awkward Jump Cuts)：若相鄰的片段使用同一個 `clip_id`，它們的 `source` 時間必須是【完全連續】的。嚴禁在連續畫面中故意漏掉幾秒鐘再接續播放 (例如上一段到 13.4s，下一段從 14.4s 開始)，這會造成嚴重的畫面跳閃失誤。若要切換，請務必換另一個不同的 `clip_id`。\n\n"
        )

        # 4. 處理微調模式 (Refinement Mode)
        if previous_timeline:
            instruction += (
                "# REFINEMENT MODE (對話式微調)\n"
                "這是一次修改任務。請參考下方的【上一版藍圖】，並針對使用者的【最新意見】進行局部修改。請盡量保持未被抱怨的片段不變。\n\n"
            )

        # 5. 處理範本模式 (Template Mode) - 【已放寬為風格與音樂參考】
        if template_dna:
            instruction += (
                "# TEMPLATE REFERENCE MODE (範本風格參考)\n"
                "使用者提供了參考範本 (Template DNA)。請將其視為『靈感來源』而非絕對限制：\n"
                "1. 【風格相近】：請分析範本的視覺氛圍與敘事結構，優先挑選與之呼應的素材。\n"
                "2. 【音樂與節奏相近】：請參考範本的剪輯步調 (例如: 密集快剪、平穩長鏡頭、卡點等)，配合當前音樂營造出類似的流動感。\n"
                "3. 保持彈性：不需要強硬對齊範本的每一秒物理切點，請以當前素材的流暢度與合理性為主。\n\n"
            )

        # 6. 輸出 Schema (Remotion Ready)
        instruction += (
            "# OUTPUT SCHEMA (嚴格 JSON 格式)\n"
            "請直接輸出 JSON Array，不要包含 Markdown 標記 (如 ```json)。每個片段的結構必須如下：\n"
            "[\n"
            "  {\n"
            "    \"clip_id\": \"檔案 ID\",\n"
            "    \"start_at\": 0.0,            // 影片在 Remotion 時間軸上的開始秒數\n"
            "    \"end_at\": 2.5,              // 影片在 Remotion 時間軸上的結束秒數\n"
            "    \"source_start\": 0.0,        // (僅限影片) 要從原素材的第幾秒開始剪\n"
            "    \"source_end\": 2.5,          // (僅限影片) 剪到原素材的第幾秒\n"
            "    \"object_position\": \"50% 50%\", // Remotion 裁切定位點，請根據素材 focus 計算\n"
            "    \"reason\": \"為何選此片段？(如：符合 user prompt，且採用了 Template 的快剪輯風格)\"\n"
            "  }\n"
            "]\n\n"
        )

        # 7. 注入數據 (Data Injection)
        prompt = (
            f"{instruction}"
            f"# INPUT DATA\n"
            f"- 🎬 目標平台: Instagram Reels / TikTok (9:16)\n"
            f"- 👤 使用者最新指令: {user_prompt}\n"
            f"- 📦 壓縮素材庫: {json.dumps(assets, ensure_ascii=False)}\n"
            f"- 🎵 配樂 DNA: {json.dumps(audio_dna, ensure_ascii=False)}\n"
        )

        if previous_timeline:
            prompt += f"- ⏪ 上一版藍圖: {json.dumps(previous_timeline, ensure_ascii=False)}\n"

        if template_dna:
            prompt += f"- 🧬 範本 DNA: {json.dumps(template_dna, ensure_ascii=False)}\n"

        if error_prompt:
            prompt += f"\n# 🚨 CRITIC ERROR LOG (系統驗證錯誤)\n請務必修正以下物理/邏輯錯誤並重新輸出：\n{error_prompt}"

        return prompt
    
    def get_intent_translation_prompt(self, user_prompt: str) -> str:
        return (
            "# ROLE\n"
            "你是一個專業的電影配樂總監。\n\n"
            "# TASK\n"
            "請分析使用者的影片剪輯需求，並決定『背景音樂的處理策略』。\n\n"
            "# RULES\n"
            "請從以下三種策略 (music_action) 挑選一種：\n"
            "1. `search`：使用者需要配樂 (指定歌曲或風格)。請在 search_query 填入能直接在【YouTube 搜尋引擎】上找到高質感音樂的關鍵字。\n"
            "   - 若指定歌曲，直接填寫「歌手 歌名」。\n"
            "   - 若只有風格，請轉換為 YouTube 創作者常用的無版權 BGM 搜尋詞 (例如：'Chill tropical house vlog bgm no copyright', 'Cinematic epic trailer music', 'Funny goofy background music')。\n"
            "2. `use_template`：使用者明確要求「使用參考範本的音樂」或「跟範本一模一樣」。\n"
            "3. `none`：使用者明確要求「無聲」、「不需要配樂」、「保留原音即可」。\n\n"
            "# OUTPUT FORMAT\n"
            "請直接輸出 JSON 格式，不可包含 markdown 標記：\n"
            "{\n"
            "  \"music_action\": \"search | use_template | none\",\n"
            "  \"search_query\": \"若是 search 才需要填寫，否則留空\"\n"
            "}\n\n"
            f"# USER PROMPT\n"
            f"使用者的需求：『{user_prompt}』\n"
        )