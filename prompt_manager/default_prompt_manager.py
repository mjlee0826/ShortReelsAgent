from prompt_manager.base_prompt_manager import BasePromptManager
from config.media_processor_config import SUBJECT_CANDIDATE_TOP_N
import json

class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。
    針對不同任務提供專門的指令，並嚴格限制 JSON 格式輸出。
    """
    
    def get_basic_media_analysis_prompt(self) -> str:
        """基本媒體分析（圖片 / 簡單短影片的全局描述與語意標籤；Qwen 本地）。"""
        return (
            "請扮演一位專業的電影攝影指導 (DP)。\n"
            "1. 請先客觀地詳細描述這份素材(圖片或影片)的主要內容與動作。\n"
            "2. 接著，請主觀評價這段素材的『鏡頭語言』與『情緒氛圍』(例如：光影、色調、構圖等)。\n"
            "3. 請依照定義分析以下語意屬性。\n"
            f"4. 請找出畫面中『最重要的前 {SUBJECT_CANDIDATE_TOP_N} 名主體』(最可能成為剪輯焦點的人或物)，"
            "依重要程度由高到低列為 subject_candidates：\n"
            "   - 每個候選含三個欄位：bbox / label / confidence。\n"
            "   - bbox 格式為 [x1, y1, x2, y2]，數值是相對影像寬高、正規化到 0–1000 的整數(x1,y1 為左上角；x2,y2 為右下角)，"
            "請只框『該單一主體』，切勿把整個畫面或多個物體一起框進去。\n"
            "   - label 為該主體的簡短中文描述(如「紅衣女子」「衝浪板」)。\n"
            "   - confidence 為 0~1 的小數，代表你判斷『它是畫面最主要主體』的把握程度，最重要者最高。\n"
            "   - 最多列 " + str(SUBJECT_CANDIDATE_TOP_N) + " 個；畫面只有單一明確主體時列 1 個即可；"
            "若完全沒有明確主體(如純風景、抽象畫面)，請將 subject_candidates 設為空陣列 []。\n"
            "【嚴格格式要求】直接輸出 JSON，不要包含 markdown 標記。\n"
            "{\n"
            "  \"caption\": \"客觀描述\",\n"
            "  \"cinematic_critique\": \"攝影評論\",\n"
            "  \"mood\": \"整體情緒，從以下選一：energetic, calm, romantic, dramatic, humorous, melancholic, inspirational, tense\",\n"
            "  \"scene_tags\": [\"場景標籤列表，可多選：outdoor, indoor, nature, urban, portrait, crowd, food, animal, vehicle, sport, night\"],\n"
            "  \"camera_angle\": \"鏡頭視角，從以下選一：close-up, medium, wide, aerial, POV, unknown\",\n"
            "  \"action_tags\": [\"動作標籤列表，可多選：dancing, talking, running, cooking, driving, playing, working, walking, performing, sitting\"],\n"
            "  \"time_of_day\": \"時段，從以下選一：golden_hour, day, dusk, night, indoor, unknown\",\n"
            "  \"subject_candidates\": [\n"
            "    {\"bbox\": [x1, y1, x2, y2], \"label\": \"主體描述\", \"confidence\": 0.9}\n"
            "  ]\n"
            "}"
        )

    def get_deep_image_analysis_prompt(self) -> str:
        """深度圖片分析（靜態圖片的進階語意分析；Gemini 雲端）。輸出為基本分析的超集（多了更深的描述）。"""
        return (
            "你是一位頂尖的電影攝影指導（DP）與視覺分析師。\n"
            "請對這張圖片進行深度語意分析，輸出比標準分析更豐富、更精確的描述。\n"
            "1. 客觀描述圖片的主要內容、人物、物件與場景細節。\n"
            "2. 主觀評析構圖、光影、色調、情緒氛圍等電影語言。\n"
            "3. 精確判斷以下所有語意屬性。\n"
            f"4. 請找出畫面中『最重要的前 {SUBJECT_CANDIDATE_TOP_N} 名主體』(最可能成為剪輯焦點的人或物)，"
            "依重要程度由高到低列為 subject_candidates：\n"
            "   - 每個候選含三個欄位：bbox / label / confidence。\n"
            "   - bbox 格式為 [x1, y1, x2, y2]，數值是相對影像寬高、正規化到 0–1000 的整數(x1,y1 為左上角；x2,y2 為右下角)，"
            "請只框『該單一主體』，切勿把整個畫面或多個物體一起框進去。\n"
            "   - label 為該主體的簡短中文描述(如「紅衣女子」「衝浪板」)。\n"
            "   - confidence 為 0~1 的小數，代表你判斷『它是畫面最主要主體』的把握程度，最重要者最高。\n"
            "   - 最多列 " + str(SUBJECT_CANDIDATE_TOP_N) + " 個；畫面只有單一明確主體時列 1 個即可；"
            "若完全沒有明確主體(如純風景、抽象畫面)，請將 subject_candidates 設為空陣列 []。\n"
            "【嚴格格式要求】直接輸出 JSON，不要包含 markdown 標記。\n"
            "{\n"
            "  \"caption\": \"詳細的客觀描述\",\n"
            "  \"cinematic_critique\": \"深度攝影評論\",\n"
            "  \"mood\": \"整體情緒，從以下選一：energetic, calm, romantic, dramatic, humorous, melancholic, inspirational, tense\",\n"
            "  \"scene_tags\": [\"場景標籤列表，可多選：outdoor, indoor, nature, urban, portrait, crowd, food, animal, vehicle, sport, night\"],\n"
            "  \"camera_angle\": \"鏡頭視角，從以下選一：close-up, medium, wide, aerial, POV, unknown\",\n"
            "  \"action_tags\": [\"動作標籤列表，可多選：dancing, talking, running, cooking, driving, playing, working, walking, performing, sitting\"],\n"
            "  \"time_of_day\": \"時段，從以下選一：golden_hour, day, dusk, night, indoor, unknown\",\n"
            "  \"subject_candidates\": [\n"
            "    {\"bbox\": [x1, y1, x2, y2], \"label\": \"主體描述\", \"confidence\": 0.9}\n"
            "  ]\n"
            "}"
        )

    def get_video_event_index_prompt(self) -> str:
        """影片事件索引（複雜影片的逐時間段多模態事件 + 音訊轉錄；Gemini）。"""
        return (
            "你現在是專業的『AI 影片剪輯大腦』與視聽分析師。\n\n"
            "【你的任務】\n"
            "1. 請全局觀看並『聆聽』這支影片，理解敘事的起承轉合與聲音情緒。\n"
            "2. 請依影片實際的時間軸(秒)，將影片拆解為數個『連續的多模態事件區塊』；若畫面上印有時間碼則以其為準。\n"
            "3. 每個區塊必須包含『視覺層 (visual_layer)』與『聽覺層 (audio_layer)』的描述。\n"
            "4. 聽覺層請記錄人說的話、人聲情緒、環境音，或配樂的起伏節奏。\n"
            "5. 在每個區塊中，請挑出一個『最關鍵的時間點 (key_timestamp)』。如果該區段有強烈的聲音爆發(如笑聲、碎裂聲)或動作高潮，請填入該精確秒數。\n"
            f"6. 在每個區塊中，請找出『該 key_timestamp 當下、畫面最重要的前 {SUBJECT_CANDIDATE_TOP_N} 名主體』，"
            "依重要程度由高到低列為 subject_candidates：\n"
            "   - 每個候選含三個欄位：bbox / label / confidence。\n"
            "   - bbox 格式為 [ymin, xmin, ymax, xmax]，數值正規化到 0–1000(ymin,xmin 為左上角；ymax,xmax 為右下角)，"
            "請只框『該單一主體』，切勿框住整個畫面或多個物體。\n"
            "   - label 為該主體的簡短中文描述；confidence 為 0~1 的小數，代表它是該區段最主要主體的把握程度。\n"
            "   - 最多列 " + str(SUBJECT_CANDIDATE_TOP_N) + " 個；若該區段無明確主體，請填空陣列 []。\n"
            "7. 同時給出整支影片的『全局語意屬性』與『全局攝影評論』。\n"
            "8. 【音訊結構化】請『聆聽』全片：逐句轉錄人聲並附時間戳 (audio_transcript.chunks，timestamp 為 [起, 訖] 秒)，"
            "給出整體 has_speech 與 spoken_language，並列出主要環境音 environmental_sounds。無人聲時 has_speech=false、transcript 留空。\n\n"
            "【嚴格格式要求】請直接輸出 JSON，不要包含 markdown 標記。時間請使用小數 (float)。\n"
            "{\n"
            "  \"cinematic_critique\": \"整支影片的運鏡與情緒氛圍評論\",\n"
            "  \"mood\": \"整體情緒，從以下選一：energetic, calm, romantic, dramatic, humorous, melancholic, inspirational, tense\",\n"
            "  \"scene_tags\": [\"場景標籤列表，可多選：outdoor, indoor, nature, urban, portrait, crowd, food, animal, vehicle, sport, night\"],\n"
            "  \"camera_angle\": \"主要鏡頭視角，從以下選一：close-up, medium, wide, aerial, POV, unknown\",\n"
            "  \"action_tags\": [\"全局動作標籤，可多選：dancing, talking, running, cooking, driving, playing, working, walking, performing, sitting\"],\n"
            "  \"time_of_day\": \"時段，從以下選一：golden_hour, day, dusk, night, indoor, unknown\",\n"
            # ── 音訊欄位(COMPLEX_AUDIO_VIA_GEMINI 開啟時由 Gemini 取代 VAD/Whisper/AudioEnv;與 TEMPLATE_ANALYSIS 保持一致)──
            "  \"has_speech\": true,\n"
            "  \"spoken_language\": \"語言代碼，如 en / zh；無人聲填空字串\",\n"
            "  \"audio_transcript\": {\n"
            "    \"text\": \"完整逐字稿；無人聲填空字串\",\n"
            "    \"language\": \"語言代碼；無人聲填空字串\",\n"
            "    \"chunks\": [ {\"text\": \"這一句話\", \"timestamp\": [0.5, 2.3]} ]\n"
            "  },\n"
            "  \"environmental_sounds\": [ {\"label\": \"環境音標籤，如 music / speech / applause / wind\", \"score\": 0.85} ],\n"
            "  \"multimodal_event_index\": [\n"
            "    {\n"
            "      \"start_time\": 0.0,\n"
            "      \"end_time\": 4.5,\n"
            "      \"visual_layer\": \"人物連續旋轉舞步，動作流暢\",\n"
            "      \"audio_layer\": \"背景音樂節奏加快，03.2秒處有明顯的重拍與歡呼聲\",\n"
            "      \"key_timestamp\": 3.2,\n"
            "      \"subject_candidates\": [\n"
            "        {\"bbox\": [ymin, xmin, ymax, xmax], \"label\": \"主體描述\", \"confidence\": 0.9}\n"
            "      ],\n"
            "      \"mood\": \"此區段情緒，從以下選一：energetic, calm, romantic, dramatic, humorous, melancholic, inspirational, tense\",\n"
            "      \"action_tags\": [\"此區段動作標籤\"]\n"
            "    }\n"
            "  ]\n"
            "}"
        )

    def get_template_analysis_prompt(self) -> str:
        """範本分析（事件索引 + 音訊轉錄 + 配樂偵測；Gemini）。"""
        return (
            "你現在是專業的『AI 影片架構與配樂分析師』，正在解析一支『範本影片』，目的是萃取它的風格與節奏供後續剪輯參考。\n\n"
            "【你的任務】\n"
            "1. 全局觀看並『聆聽』這支範本，理解它的敘事節奏、情緒氛圍與配樂風格。\n"
            "2. 依影片實際時間軸(秒)，拆解為數個『連續的多模態事件區塊』；每塊含 visual_layer 與 audio_layer 描述，並挑一個 key_timestamp。\n"
            "3. 逐句轉錄人聲並附時間戳 (audio_transcript.chunks，timestamp 為 [起, 訖] 秒)；無人聲時 transcript 各欄留空。\n"
            "4. 給出整支影片的『全局攝影評論』與『全局情緒 / 場景 / 動作標籤』。\n"
            "5. 【配樂偵測 music_analysis】分析範本使用的配樂：music_style(自由描述編制 / 風格)、genre(從清單擇一)、"
            "音樂情緒 mood、是否有歌聲 has_vocals；並『盡力猜測』歌名 song_guess(title / artist) 並附 confidence(0~1)。\n"
            "   ⚠️ song_guess 為『最佳猜測、可能有誤』：不確定的欄位請留空、confidence 給低分，切勿杜撰歌名。\n\n"
            "【嚴格格式要求】請直接輸出 JSON，不要包含 markdown 標記。時間請使用小數 (float)。\n"
            "{\n"
            "  \"cinematic_critique\": \"整支範本的運鏡與情緒氛圍評論\",\n"
            "  \"mood\": \"整體情緒，從以下選一：energetic, calm, romantic, dramatic, humorous, melancholic, inspirational, tense\",\n"
            "  \"scene_tags\": [\"場景標籤，可多選：outdoor, indoor, nature, urban, portrait, crowd, food, animal, vehicle, sport, night\"],\n"
            "  \"action_tags\": [\"全局動作標籤，可多選：dancing, talking, running, cooking, driving, playing, working, walking, performing, sitting\"],\n"
            # ── 音訊轉錄(與 VIDEO_EVENT_INDEX 的 audio_transcript 結構保持一致)──
            "  \"audio_transcript\": {\n"
            "    \"text\": \"完整逐字稿；無人聲填空字串\",\n"
            "    \"language\": \"語言代碼，如 en / zh；無人聲填空字串\",\n"
            "    \"chunks\": [ {\"text\": \"這一句話\", \"timestamp\": [0.5, 2.3]} ]\n"
            "  },\n"
            # ── 配樂偵測(範本專屬;歌名為最佳猜測,務必附 confidence)──
            "  \"music_analysis\": {\n"
            "    \"music_style\": \"自由描述曲風 / 編制，如 'lo-fi chill hip-hop, mellow piano'\",\n"
            "    \"genre\": \"從以下擇一：pop, rock, hiphop, electronic, jazz, classical, ambient, folk, cinematic, other\",\n"
            "    \"mood\": \"音樂情緒，從以下選一：energetic, calm, romantic, dramatic, humorous, melancholic, inspirational, tense\",\n"
            "    \"has_vocals\": true,\n"
            "    \"song_guess\": {\"title\": \"猜測歌名(不確定留空)\", \"artist\": \"猜測歌手(不確定留空)\", \"confidence\": 0.0}\n"
            "  },\n"
            "  \"multimodal_event_index\": [\n"
            "    {\n"
            "      \"start_time\": 0.0,\n"
            "      \"end_time\": 4.5,\n"
            "      \"visual_layer\": \"畫面動作描述\",\n"
            "      \"audio_layer\": \"配樂 / 人聲 / 環境音的起伏描述\",\n"
            "      \"key_timestamp\": 3.2,\n"
            "      \"mood\": \"此區段情緒\",\n"
            "      \"action_tags\": [\"此區段動作標籤\"]\n"
            "    }\n"
            "  ]\n"
            "}"
        )

    def get_director_blueprint_prompt(self, user_prompt, assets, audio_dna, template_dna=None, previous_timeline=None, error_prompt=""):
        """導演剪輯藍圖（把素材庫編排成 Remotion 可渲染的 JSON 剪輯藍圖）。"""
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
            "0. 【語意排列原則 (Semantic Ordering)】：\n"
            "   - 依 `mood` 設計情緒弧線（如：calm → energetic → dramatic → calm）。\n"
            "   - 利用 `scene_tags` 與 `actions` 確保相鄰片段有場景或動作的多樣性，避免連續同類素材。\n"
            "   - 利用 `motion` 搭配音樂節奏選剪輯點：dynamic 素材對應重拍，static 素材對應安靜段落。\n"
            "1. 【節奏與變速 (Speed Ramping)】：\n"
            "   - 善用 `playback_rate` 調整節奏 (0.5=慢動作, 2.0=快轉)。與其將連續動作切碎，不如利用變速來對齊音樂的重拍 (onsets)。\n"
            "   - ⚠️ 重要約束：`(source_end - source_start) / playback_rate` 必須等於 `end_at - start_at`。\n"
            "     例如：source 取 4 秒，playback_rate=2.0，則 end_at - start_at 必須為 2.0 秒。\n"
            "2. 【空間裁切與運鏡 (Crop & Zoom)】：\n"
            "   - 輸出平台為 9:16 直式。必須參考素材的 `bbox` 數據計算 `object_position`：取中心點 ((x1+x2)/2)% ((y1+y2)/2)%，嚴禁無腦填寫 '50% 50%'。\n"
            "   - `bbox` 已是系統綜合『信心與 9:16 可裁性』自動選定的最佳主體框，預設直接用它定位。\n"
            "   - 若素材另附 `subjects`(候選主體清單，含 label/conf/各自 bbox；影片則見各 event 的 subject_candidates)，"
            "且使用者意圖或情緒明確指向清單中『另一個』主體，請改用該候選的 bbox 中心計算 `object_position`。\n"
            "   - 若 `crop` 為 'not_recommended'，優先考慮使用縮放或跳過該素材。\n"
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
            "1. 全局配樂 (bgm_track)：實際 BGM 檔案一律來自【配樂 DNA】，請據此設定 track_id 與起始時間。"
            "（【範本 DNA】的配樂僅供風格參考，不是可播放的音檔，切勿拿來當 BGM。）\n"
            "2. 智慧人聲保留邏輯：檢視素材的 `audio.transcript` (逐字稿，含 `text` 與帶時間戳的 `chunks`) 或 `events.audio_layer` (聲音事件)。\n"
            "   - 若有人聲對話或重要口白：必須保留原音 (`clip_volume`: 1.0)，並將該片段的配樂降低以避讓 (`bgm_volume`: 0.2)。\n"
            "   - 善用 `audio.transcript.chunks` 的 `timestamp` ([起, 訖] 秒)：把 `overlay_text` 字幕與 `bgm_volume` ducking 精準對齊到實際講話的時間點，而非整段一刀切。\n"
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
                "參考範本的視覺氛圍與節奏步調。不需要強硬對齊範本的每一秒物理切點，請以當前素材的流暢度與你身為導演的專業判斷為主。\n"
                "若【範本 DNA】含 `music_dna` (配樂偵測：music_style / genre / 情緒)，請用它校準整體情緒弧線與卡點節奏感；"
                "但實際 BGM 仍以【配樂 DNA】為準，範本配樂只是風格定錨、不是可播放的音檔。\n\n"
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
    
    def get_music_search_query_prompt(self, user_prompt: str) -> str:
        """音樂搜尋關鍵字（把使用者需求轉成精準的配樂搜尋詞）。"""
        return (
            "# ROLE\n"
            "你是一個專業的電影配樂總監。\n\n"
            "# TASK\n"
            "根據使用者的影片剪輯需求，萃取最適合的音樂搜尋關鍵字。\n\n"
            "# RULES\n"
            "1. 若使用者指名特定歌手或歌曲，直接輸出「歌手 歌名」(例如: \"Sia Snowman\", \"周杰倫 稻香\")。\n"
            "2. 若使用者描述情緒、氛圍或風格，輸出英文音樂關鍵字 (例如: \"chill summer tropical house\", \"epic cinematic trailer\", \"funny goofy upbeat\")。\n"
            "3. 若 Prompt 完全未提及配樂偏好，根據整體影片氛圍推測合適的搜尋詞。\n\n"
            "# OUTPUT FORMAT\n"
            "請直接輸出 JSON 格式，不可包含 Markdown 標記：\n"
            "{\"search_query\": \"...\"}\n\n"
            f"# USER PROMPT\n"
            f"使用者的需求：『{user_prompt}』\n"
        )