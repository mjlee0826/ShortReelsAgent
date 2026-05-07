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
            "你是一位具備高度藝術直覺的 AI 電影導演與 Remotion 渲染架構師。\n"
            "你的任務是將素材庫編排成一份具備電影感的 JSON 剪輯藍圖，這份藍圖將直接驅動 React/Remotion 引擎進行精準的畫面合成與混音。\n\n"
        )

        # 2. 最高指導原則 (User Intent)
        instruction += (
            "# CORE OBJECTIVE (最高指導原則)\n"
            "【User Overrides Everything】：使用者的需求 (User Prompt) 是絕對的最高準則！若指令要求特定風格（如：搞笑、悲傷、快節奏、畫中畫），必須強行蓋過素材或音樂原本的氛圍來滿足使用者。\n\n"
        )

        # 3. 剪輯工具箱與決策邏輯 (Remotion Capabilities)
        instruction += (
            "# DECISION GUIDELINES (導演剪輯工具箱與邏輯)\n"
            "身為導演，你必須靈活運用以下 Remotion 渲染能力來提升影片張力：\n"
            "1. 【節奏與變速 (Speed Ramping)】：\n"
            "   - 善用 `playback_rate` 調整節奏 (0.5=慢動作, 2.0=快轉)。與其將連續動作切碎，不如利用變速來對齊音樂的重拍 (onsets)。\n"
            "   - ⚠️ 重要約束：`(source_end - source_start) / playback_rate` 必須等於 `end_at - start_at`。\n"
            "     例如：source 取 4 秒，playback_rate=2.0，則 end_at - start_at 必須為 2.0 秒。\n"
            "2. 【空間裁切與運鏡 (Crop & Zoom)】：\n"
            "   - 輸出平台為 9:16 直式。必須參考素材的 `focus` 數據計算 `object_position`，嚴禁無腦填寫 '50% 50%'。\n"
            "   - 靜態照片或慢節奏畫面，可使用 `scale` (例如 1.1 或 1.2) 搭配前端動畫營造緩慢推進 (Zoom-in) 的視覺張力。\n"
            "3. 【轉場效果 (Transitions)】：\n"
            "   - 素材間若情緒或場景落差大，請設定 `transition_in` (如 'fade', 'wipe', 'slide')。\n"
            "   - 若是快節奏的動作卡點剪輯，請保持 'none' (硬切)。\n"
            "4. 【視覺風格與字幕 (Aesthetics & Text)】：\n"
            "   - 根據氛圍設定 `filter` (如 'none', 'cinematic', 'grayscale', 'blur')。\n"
            "   - 若有重要對話 (參考 vocal) 或需要綜藝效果，請在 `overlay_text` 填寫要顯示的字幕。\n"
            "5. 【畫中畫疊加 (Picture-in-Picture)】：\n"
            "   - 若使用者要求，或你想在主畫面旁補充視角，可使用 `pip_video` 屬性疊加另一個畫面。\n"
            "6. 【嚴禁假剪輯與突兀跳剪 (No Chopping & Jump Cuts)】：\n"
            "   - 絕對不可將同一支影片的連續畫面硬切成多個 JSON 物件！若要連續播放，請合併為『一個』長片段。\n"
            "   - 相鄰的兩個片段 `clip_id` 必須不同。嚴禁在連續畫面中故意漏掉幾秒鐘再接續播放，以免造成畫面跳閃。\n\n"
        )

        # 【新增】配樂與混音專屬守則
        instruction += (
            "# AUDIO & BGM GUIDELINES (配樂與原音混音守則)\n"
            "1. 全局配樂 (bgm_track)：請從【配樂 DNA】或【範本 DNA】中挑選合適的音樂檔案作為全局 BGM，並設定其起始時間。\n"
            "2. 智慧人聲保留邏輯：檢視素材的 `audio.vocal` (講話內容) 或 `events.audio_layer` (聲音事件)。\n"
            "   - 若有人聲對話或重要口白：必須保留原音 (`clip_volume`: 1.0)，並將該片段的配樂降低以避讓 (`bgm_volume`: 0.2)。\n"
            "   - 若只有無意義環境音或純風景：請靜音原片 (`clip_volume`: 0.0)，讓配樂成為主體 (`bgm_volume`: 1.0)。\n\n"
        )

        # 4. 處理模式 (Refinement / Template)
        if previous_timeline:
            instruction += (
                "# REFINEMENT MODE (對話式微調)\n"
                "這是一次修改任務。請參考下方的【上一版藍圖】，針對使用者的【最新意見】進行局部修改。若無提及的部分請保留原樣。\n\n"
            )

        if template_dna:
            instruction += (
                "# TEMPLATE REFERENCE MODE (範本風格參考)\n"
                "參考範本的視覺氛圍與節奏步調。不需要強硬對齊範本的每一秒物理切點，請以當前素材的流暢度與你身為導演的專業判斷為主。\n\n"
            )

        # 5. 輸出 Schema (Remotion Ready JSON)
        # 【修改】外層改為 Object，支援 bgm_track 欄位
        instruction += (
            "# OUTPUT SCHEMA (Remotion 渲染專用 JSON 格式)\n"
            "請直接輸出 JSON Object，不要包含 Markdown 標記。格式必須嚴格如下：\n"
            "{\n"
            "  \"bgm_track\": {\n"
            "    \"track_id\": \"配樂檔案的 ID (若不使用配樂請填 null)\",\n"
            "    \"start_at\": 0.0,          // 整個影片時間軸上，音樂開始播放的秒數 (通常為 0.0)\n"
            "    \"source_start\": 0.0,      // 從音樂檔案的第幾秒開始擷取\n"
            "    \"volume\": 1.0             // 音樂基礎音量 (0.0~1.0)\n"
            "  },\n"
            "  \"timeline\": [\n"
            "    {\n"
            "      \"clip_id\": \"檔案 ID\",\n"
            "      \"start_at\": 0.0,             // 總時間軸上的開始秒數\n"
            "      \"end_at\": 3.5,               // 總時間軸上的結束秒數\n"
            "      \"source_start\": 5.0,         // 素材擷取起點(秒)\n"
            "      \"source_end\": 8.5,           // 素材擷取終點(秒)\n"
            "      \"playback_rate\": 1.0,        // 播放速度 (預設 1.0)\n"
            "      \"object_position\": \"44% 77%\", // 裁切定位點 (依據 focus 計算)\n"
            "      \"scale\": 1.0,                // 縮放比例 (1.0 不縮放，1.2 放大 20%)\n"
            "      \"filter\": \"none\",            // CSS 濾鏡 (none, grayscale, cinematic, blur)\n"
            "      \"transition_in\": \"none\",     // 進場轉場 (none, fade, slide)\n"
            "      \"clip_volume\": 0.8,          // 原音音量 (0.0=靜音, 1.0=最大)\n"
            "      \"bgm_volume\": 1.0,           // 當播到此片段時，全局 BGM 的動態音量權重 (這就是 Audio Ducking)\n"
            "      \"overlay_text\": \"\",          // 畫面上要疊加的字幕或花字 (無則留空)\n"
            "      \"pip_video\": {               // (選填) 畫中畫設定，若無畫中畫需求請設為 null\n"
            "         \"clip_id\": \"b_roll.mp4\",  // 子畫面的檔案 ID\n"
            "         \"source_start\": 0.0,\n"
            "         \"position\": \"top_right\" // 位置 (top_right, bottom_left 等)\n"
            "      },\n"
            "      \"reason\": \"請說明你的導演決策，包含轉場、變速或混音的考量\"\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
        )

        # 6. 注入數據 (Data Injection)
        # ... (這裡維持原樣) ...
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
            prompt += f"\n# 🚨 CRITIC ERROR LOG (系統驗證錯誤)\n請務必修正以下物理或邏輯錯誤並重新輸出：\n{error_prompt}"

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