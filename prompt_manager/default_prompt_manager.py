import json

from config.director_config import DIRECTOR_CASTING_POOL_TARGET
from config.media_processor_config import SUBJECT_CANDIDATE_TOP_N
from prompt_manager.base_prompt_manager import BasePromptManager, PromptSpec
from prompt_manager.schemas import (
    BasicMediaSemantics,
    CastingSelection,
    DirectorBlueprint,
    MusicSearchQuery,
    TemplateAnalysisSemantics,
    VideoEventIndexSemantics,
    schema_to_text,
)


class DefaultPromptManager(BasePromptManager):
    """
    系統預設的 Prompt 管理器。

    設計原則：**格式交給 schema、文字專注心法**。Gemini 路徑把 PromptSpec.schema 交給
    ``response_schema`` 強制結構與 enum，故 prompt 文字不再手寫 JSON 範例（依 Gemini 官方建議，
    重複 schema 反而降低品質）；本地 Qwen 無 structured-output，basic 一支以 ``schema_to_text``
    把同一份 schema 序列化進文字。所有可列舉值同源於 ``prompt_manager.schemas`` 的 enum。
    """

    def get_basic_media_analysis_prompt(self) -> PromptSpec:
        """基本媒體分析（圖片 / 簡單短影片的全局描述與語意標籤；Qwen 本地，純文字路徑）。"""
        # Qwen 無 response_schema 能力：心法 + 由 schema 序列化的格式說明（單一來源、不另手抄）
        text = (
            "# 角色\n"
            "你是一位專業的電影攝影指導 (DP)，正在為自動剪輯系統標註素材。\n\n"
            "# 分析重點\n"
            "1. 你的描述是給「機器導演」當剪輯依據，不是給人看的影評——精準、可決策優先於華麗辭藻。\n"
            "2. 寧缺勿造：不確定的欄位保守填或留空，尤其主體框；編造會誤導下游剪輯。\n"
            f"3. 找出畫面最重要的前 {SUBJECT_CANDIDATE_TOP_N} 名主體 (subject_candidates)，依重要程度由高到低排序：\n"
            "   - 只框『單一主體』、服務 9:16 直式裁切，切勿把整個畫面或多個物體一起框進去。\n"
            "   - bbox 用 [x1, y1, x2, y2]（左上→右下），數值正規化到 0–1000 整數。\n"
            "   - 純風景 / 抽象畫面無明確主體時，subject_candidates 填空陣列。\n"
            "4. 本任務在本地小模型上執行，描述務必扼要——結構完整優先於長度。\n\n"
            f"{schema_to_text(BasicMediaSemantics)}"
        )
        return PromptSpec(text=text, schema=None)

    def get_deep_image_analysis_prompt(self) -> PromptSpec:
        """深度圖片分析（靜態圖片的進階語意分析；Gemini 雲端）。與基本分析同 schema、更細描述。"""
        text = (
            "# 角色\n"
            "你是頂尖的電影攝影指導 (DP) 與視覺分析師，正在對單張圖片做深度語意分析。\n\n"
            "# 分析重點\n"
            "1. 你的描述是給「機器導演」當剪輯依據——精準、可決策優先；身為深度分析，描述應比基本分析更細緻精確。\n"
            "2. caption 客觀描述內容、人物、物件與場景細節；cinematic_critique 主觀評析構圖、光影、色調、情緒氛圍等電影語言。\n"
            "3. 寧缺勿造：不確定的欄位保守填或留空。\n"
            f"4. 找出畫面最重要的前 {SUBJECT_CANDIDATE_TOP_N} 名主體，依重要程度由高到低排序：\n"
            "   - 只框『單一主體』、服務 9:16 直式裁切，切勿框住整個畫面或多個物體。\n"
            "   - bbox 用 [x1, y1, x2, y2]（左上→右下），數值正規化到 0–1000 整數。\n"
            "   - 無明確主體時填空陣列。"
        )
        return PromptSpec(text=text, schema=BasicMediaSemantics)

    def get_video_event_index_prompt(self) -> PromptSpec:
        """影片事件索引（複雜影片的逐時間段多模態事件 + 音訊轉錄；Gemini）。"""
        text = (
            "# 角色\n"
            "你是專業的「AI 影片剪輯大腦」與視聽分析師。\n\n"
            "# 分析重點\n"
            "1. 全局觀看並『聆聽』整支影片，理解敘事的起承轉合與聲音情緒。\n"
            "2. ⚠️ 時間戳的準確度是這份分析的命脈：事件起訖 (start_time / end_time)、關鍵點 (key_timestamp)、\n"
            "   逐句轉錄 (audio_transcript.chunks) 的秒數都必須貼合影片實際時間軸——導演靠它卡剪輯點、\n"
            "   對齊字幕與配樂避讓；時間錯了，描述再華麗也無用。若畫面印有時間碼，以其為準。\n"
            "3. 依時間軸把影片拆成數個『連續的多模態事件區塊』，每塊都要有：\n"
            "   - visual_layer（畫面動作）與 audio_layer（人聲 / 配樂 / 環境音的起伏）雙層描述。\n"
            "   - key_timestamp：該區段聲音爆發（笑聲、碎裂聲）或動作高潮的精確秒數。\n"
            f"   - subject_candidates：key_timestamp 當下畫面最重要的前 {SUBJECT_CANDIDATE_TOP_N} 名主體，依信心由高到低排序；\n"
            "     只框『單一主體』，bbox 用 [ymin, xmin, ymax, xmax]，數值正規化到 0–1000 整數；無明確主體填空陣列。\n"
            "4. 音訊結構化：逐句轉錄人聲並附 [起, 訖] 秒時間戳；給出整體 has_speech 與 spoken_language；\n"
            "   列出主要環境音。無人聲時 has_speech=false、轉錄留空。\n"
            "5. 同時給出整支影片的全局攝影評論 (cinematic_critique) 與全局語意標籤。\n"
            "6. 寧缺勿造：不確定的主體框 / 標籤保守處理。"
        )
        return PromptSpec(text=text, schema=VideoEventIndexSemantics)

    def get_template_analysis_prompt(self) -> PromptSpec:
        """範本分析（事件索引 + 音訊轉錄 + 配樂偵測；Gemini）。"""
        text = (
            "# 角色\n"
            "你是專業的「AI 影片架構與配樂分析師」，正在解析一支『範本影片』。\n\n"
            "# 分析重點\n"
            "1. 你在拆解一支風格範本：目的是萃取『節奏感、情緒曲線、配樂風格』供後續剪輯模仿，\n"
            "   不是逐秒複製它的物理切點。\n"
            "2. 全局觀看並『聆聽』，理解敘事節奏、情緒氛圍與配樂風格。\n"
            "3. 依時間軸拆成數個『連續的多模態事件區塊』，每塊含 visual_layer 與 audio_layer 描述。\n"
            "4. 逐句轉錄人聲並附 [起, 訖] 秒時間戳；無人聲時轉錄留空。\n"
            "5. 配樂偵測 (music_analysis)：描述曲風 / 編制 (music_style)、分類 (genre)、音樂情緒、是否有歌聲；\n"
            "   並『盡力猜測』歌名 (song_guess)。\n"
            "   ⚠️ song_guess 為最佳猜測、可能有誤：不確定的欄位務必留空、confidence 給低分，切勿杜撰歌名。\n"
            "6. 給出整支範本的全局攝影評論與全局情緒 / 場景 / 動作標籤。"
        )
        return PromptSpec(text=text, schema=TemplateAnalysisSemantics)

    def get_director_blueprint_prompt(self, user_prompt, assets, audio_dna, template_dna=None,
                                      previous_timeline=None, error_prompt="") -> PromptSpec:
        """導演剪輯藍圖（把素材庫編排成 Remotion 可渲染的 JSON 剪輯藍圖）。"""
        # 1. 角色與最高指導原則
        instruction = (
            "# 角色\n"
            "你是具備藝術直覺的 AI 電影導演與 Remotion 渲染架構師。你的任務是把素材庫編排成一份\n"
            "具電影感、卡得住音樂、混音合理的 JSON 剪輯藍圖，直接驅動 Remotion 引擎渲染。\n\n"
            "# 最高指導原則\n"
            "【User Overrides Everything】使用者指令是絕對的最高準則。若要求特定風格（搞笑 / 悲傷 / \n"
            "快節奏 / 畫中畫），必須蓋過素材或音樂原本的氛圍來滿足使用者。\n\n"
        )

        # 2. 剪輯心法（落實短影音剪輯原則：選材 / hook / 節奏 / 卡點 / 弧線 / 多樣 / 混音 / 定位 / 物理鐵律）
        instruction += (
            "# 剪輯心法\n"
            "1. 選材：優先採用 aes（美學）與 tech（技術畫質）分數高的素材；分數低的留作補位或捨棄。\n"
            "2. 開場 Hook：前 3 秒放最強、對比最大的素材抓住觀眾——短影音前 3 秒留不住人就直接流失。\n"
            "3. 節奏 (ASL)：高能量段用短鏡頭快切堆張力，抒情 / 情緒段用長鏡頭沉澱。要延長動作優先用\n"
            "   playback_rate 變速對齊音樂，而非把連續畫面切碎。\n"
            "4. 卡點：剪輯點盡量對齊配樂 DNA 的 analysis.beats（重拍）與 analysis.onsets（起音）時間點。\n"
            "5. 情緒弧線：用素材的 mood 編排起落（如 calm→energetic→dramatic→payoff），不要平鋪直敘。\n"
            "6. 多樣性：用 scene_tags 與 actions 確保相鄰片段的場景或動作有變化，避免連續同類素材。\n"
            "7. 混音 (Ducking)：有人聲對話（看 audio.transcript 或 events.audio_layer）必須保留原音\n"
            "   (clip_volume 高) 並壓低該段 BGM 避讓 (bgm_volume 低)；用 transcript.chunks 的時間戳把字幕與\n"
            "   避讓精準對齊講話時段。純風景 / 無意義環境音則原片靜音 (clip_volume=0)、讓 BGM 主導 (bgm_volume=1)。\n"
            "8. 裁切定位：輸出為 9:16 直式。依素材 bbox（{x1,y1,x2,y2}，0–100 百分比）算 object_position：\n"
            "   取中心點字串 \"((x1+x2)/2)% ((y1+y2)/2)%\"，嚴禁無腦填 '50% 50%'。若素材另附 subjects 候選清單，\n"
            "   且使用者意圖 / 情緒指向其中『另一個』主體，改用該候選 bbox 中心。crop 為 'not_recommended'\n"
            "   時優先改用縮放或跳過該素材。\n"
            "9. 物理鐵律（違反會被系統 Critic 打回重做）：\n"
            "   - 時間軸嚴格首尾相接、零間隙零重疊：前一段的 end_at 必須等於下一段的 start_at。\n"
            "   - 變速一致性：(source_end - source_start) / playback_rate 必須等於 (end_at - start_at)。\n"
            "   - source_end 不得超過該素材的原始長度 dur。\n"
            "   - 嚴禁假剪輯：絕不可把同一支影片的連續畫面硬切成多個片段（相鄰片段 clip_id 必須不同）；\n"
            "     要連續播放就合併成『一個』長片段。\n"
            "   - clip_id 必須與素材庫某筆 id 逐字完全相同：原樣照抄（含 raw/ 或 standardized/ 前綴與 _std\n"
            "     後綴），嚴禁改寫前綴、去掉 _std、簡化或自行拼湊路徑；填了素材庫不存在的 id 會被打回重做。\n\n"
        )

        # 3. 工具箱（僅列前端真正支援的能力，不承諾不存在的效果）
        instruction += (
            "# 工具箱（僅列前端真正支援的能力）\n"
            "- transition_in：硬切用 'none'；情緒 / 場景落差大時用 'fade'（交叉淡入）。\n"
            "- filter：依氛圍選 'none' / 'cinematic' / 'grayscale' / 'blur'。\n"
            "- scale：可放大（如 1.1~1.2）做構圖微調（注意：為靜態縮放，非動態推鏡，勿描述成緩慢推進）。\n"
            "- text_overlay：有重要對話或需綜藝效果時加字幕（物件；無字幕則設 null）。text 為字幕內容；\n"
            "  vertical_position（0=畫面頂、100=畫面底，水平自動置中）依該段主體 bbox 放在『不擋主體』處——\n"
            "  主體在畫面下半就取小值偏上、在上半就取大值偏下；上下邊界系統會自動夾進 safe-area，不必自己算平台 UI；\n"
            "  size / color / outline / background / animation 控制樣式，整支盡量沿用一致的 size / color / outline，避免每段不同顯得廉價。\n"
            "- pip_video：需畫中畫時疊加另一畫面，position 僅支援 'top_right' / 'bottom_left'。\n"
            "- reason：每個片段請『先』在 reason 寫下導演決策考量（選材 / 轉場 / 變速 / 混音），再填其餘參數。\n\n"
        )

        # 4. 配樂守則（track_id 由後端注入，LLM 不填）
        instruction += (
            "# 配樂\n"
            "- bgm_track 的實際音檔由系統依【配樂 DNA】注入，你**不要**填 track_id；只需決定 start_at\n"
            "  （通常 0.0）、source_start 與 volume。\n"
            "- 【範本 DNA】的配樂（若有）僅供風格參考，不是可播放的音檔，切勿拿來當 BGM。\n\n"
        )

        # 5. 處理模式（對話式微調 / 範本風格參考）
        if previous_timeline:
            instruction += (
                "# 微調模式\n"
                "這是一次修改任務：參考下方【上一版藍圖】，只針對使用者的【最新指令】做局部修改，\n"
                "未提及的部分保留原樣。\n\n"
            )
        if template_dna:
            instruction += (
                "# 範本風格參考\n"
                "參考範本的視覺氛圍與節奏步調，但不需逐秒對齊範本的物理切點，以當前素材的流暢度與你的\n"
                "專業判斷為主。若【範本 DNA】含 music_dna（配樂偵測），用它校準整體情緒弧線與卡點節奏感；\n"
                "但實際 BGM 仍以【配樂 DNA】為準。\n\n"
            )

        # 6. 輸入欄位說明（素材庫為精簡縮寫，給導演一份完整欄位字典；對齊 ContextCompressor 實際輸出）
        instruction += (
            "# 素材庫欄位說明（assets 為精簡縮寫）\n"
            "通用：id=素材ID(即 clip_id；填回 clip_id 時務必『原樣照抄』，含 raw/ 或 standardized/ 前綴與 _std 後綴，"
            "不可更動前綴或去掉 _std) / type=image|video / res=解析度{w,h} / time=拍攝時間 / geo=GPS地點。\n"
            "品質：aes,tech=美學,技術畫質分（選材優先取高分）。\n"
            "語意：cap=客觀描述 / critique=攝影評論 / mood=情緒 / scene_tags=場景 / cam=視角 / actions=動作 / tod=時段。\n"
            "視覺特徵：bright=亮度 / color_temp=色溫(warm/cool/neutral) / colors=主色清單。\n"
            "主體與裁切：bbox=最佳主體框(0–100百分比,{x1,y1,x2,y2}) / crop=9:16可裁性 /\n"
            "  subjects=候選主體清單(各含 label/conf/bbox) / face_count=臉數 / face_ratio=最大臉佔比(越大越特寫)。\n"
            "影片專屬：dur=時長(秒) / fps / motion=動態強度 / has_speech,lang=語音 / cuts=場景切點 /\n"
            "  audio=逐字稿(transcript.chunks 帶時間戳)與環境音(env) / is_complex=複雜影片 / events=逐段視聽事件(僅複雜影片)。\n\n"
        )

        # 7. 注入實際資料
        prompt = (
            f"{instruction}"
            "# 輸入資料\n"
            "- 🎬 目標平台: Instagram Reels / TikTok (9:16)\n"
            f"- 👤 使用者最新指令: {user_prompt}\n"
            f"- 📦 素材庫: {json.dumps(assets, ensure_ascii=False)}\n"
            f"- 🎵 配樂 DNA: {json.dumps(audio_dna, ensure_ascii=False)}\n"
        )
        if previous_timeline:
            prompt += f"- ⏪ 上一版藍圖: {json.dumps(previous_timeline, ensure_ascii=False)}\n"
        if template_dna:
            prompt += f"- 🧬 範本 DNA: {json.dumps(template_dna, ensure_ascii=False)}\n"
        if error_prompt:
            prompt += (
                "\n# 🚨 Critic 驗證錯誤（務必修正以下物理 / 邏輯錯誤並重新輸出）\n"
                f"{error_prompt}"
            )

        return PromptSpec(text=prompt, schema=DirectorBlueprint)

    def get_director_casting_prompt(self, user_prompt, casting_cards, audio_dna,
                                    template_dna=None) -> PromptSpec:
        """導演選角（兩階段第一段）：從精簡卡片粗篩出一個『候選池』，只輸出 id。"""
        # 1. 角色與職責邊界（只做粗篩出候選池，最終定剪 / 排序 / 時間軸全留給第二段）
        instruction = (
            "# 角色\n"
            "你是 AI 電影導演的『選角』大腦。面對一整櫃素材，你只負責一件事：粗篩出一個『候選池』——\n"
            "把『有機會用到』的素材都留下、只剔除明顯不適合的，輸出它們的 id。最終要用哪些、怎麼排、\n"
            "精準剪輯點 / 裁切 / 變速 / 字幕 / 混音，全部交給後續精修階段在這個池子裡自由發揮。\n"
            "⚠️ 你是『粗篩』不是『定剪』：寧可多留、不要早剪——把抉擇權留給更強的精修階段。\n\n"
            "# 最高指導原則\n"
            "【User Overrides Everything】使用者指令是絕對最高準則：要求的風格 / 主題 / 節奏，必須蓋過\n"
            "素材或音樂原本的氛圍來滿足。\n\n"
        )
        # 2. 粗篩心法（顧的是「池子夠不夠用、有沒有誤殺」，不是定剪）
        instruction += (
            "# 粗篩心法\n"
            f"1. 池子大小：目標保留『約 {DIRECTOR_CASTING_POOL_TARGET} 個』候選素材。素材夠多時就盡量補滿，\n"
            "   給精修階段充足的選擇空間；寧可多留幾個邊際素材，也不要在這步就砍光。\n"
            "2. 只剔明顯不適合：剔除『明顯不相關、重複、或品質太差（aes/tech 很低又 crop not_recommended）』的；\n"
            "   只要『有機會用到』就留著——是否真的用、用哪段，交給第二段。\n"
            "3. 切題：依使用者指令，對照素材的 cap / transcript_text / event_digest 判斷相關性。\n"
            "4. 池子要湊得出好片：確保候選池涵蓋夠強的開場素材、情緒（mood）能鋪出起落、場景與動作\n"
            "   （scene_tags / actions）夠多樣——別讓整池都同一種。\n"
            "5. 複雜影片：event_digest 顯示片內多個畫面 beat，只要有可用片段就留；精準切哪段由第二段決定。\n"
            "6. 排序：把『最相關 / 最該用』的排在 selected_ids 前面（供必要時取捨用，不是播放順序）。\n\n"
        )
        # 3. 卡片欄位字典（卡片為精簡縮寫，對齊 ContextCompressor.to_casting_cards 輸出）
        instruction += (
            "# 素材卡片欄位說明（assets 為精簡縮寫）\n"
            "id=素材ID（輸出 selected_ids 時務必原樣照抄，含 raw/ 或 standardized/ 前綴與 _std 後綴）/ "
            "type=image|video / aes,tech=美學,技術畫質分 / cap=客觀描述 / mood=情緒 / scene_tags=場景 / "
            "actions=動作 / crop=9:16可裁性 / time=拍攝時間 / geo=地點。\n"
            "影片專屬：dur=時長(秒) / motion=動態強度 / has_speech=是否有人聲 / "
            "transcript_text=完整逐字稿 / event_digest=片內各事件的畫面動作摘要。\n\n"
        )
        # 4. 範本風格參考（選填）
        if template_dna:
            instruction += (
                "# 範本風格參考\n"
                "參考範本的視覺氛圍與節奏步調來決定選材傾向；若含 music_dna，用它校準整體情緒。\n\n"
            )
        # 5. 注入實際資料
        prompt = (
            f"{instruction}"
            "# 輸入資料\n"
            "- 🎬 目標平台: Instagram Reels / TikTok (9:16)\n"
            f"- 👤 使用者最新指令: {user_prompt}\n"
            f"- 📦 素材卡片庫: {json.dumps(casting_cards, ensure_ascii=False)}\n"
            f"- 🎵 配樂 DNA: {json.dumps(audio_dna, ensure_ascii=False)}\n"
        )
        if template_dna:
            prompt += f"- 🧬 範本 DNA: {json.dumps(template_dna, ensure_ascii=False)}\n"
        return PromptSpec(text=prompt, schema=CastingSelection)

    def get_music_search_query_prompt(self, user_prompt: str, asset_mood_summary: str = "") -> PromptSpec:
        """音樂搜尋關鍵字（把使用者需求轉成精準的配樂搜尋詞；未指定時依素材氛圍推測）。"""
        text = (
            "# 角色\n"
            "你是專業的電影配樂總監，要為一支短影片挑選最適合的配樂搜尋關鍵字。\n\n"
            "# 規則\n"
            "1. 若使用者指名特定歌手或歌曲，直接輸出「歌手 歌名」（如 \"Sia Snowman\"、\"周杰倫 稻香\"）。\n"
            "2. 若使用者描述情緒 / 氛圍 / 風格，輸出英文音樂關鍵字\n"
            "   （如 \"chill summer tropical house\"、\"epic cinematic trailer\"、\"funny goofy upbeat\"）。\n"
            "3. 若使用者完全沒提配樂偏好，依『素材整體氛圍』推測合適的搜尋詞。\n\n"
            f"# 使用者需求\n『{user_prompt}』\n\n"
            f"# 素材整體氛圍（使用者未指定配樂時的推測依據）\n{asset_mood_summary or '（無）'}\n"
        )
        return PromptSpec(text=text, schema=MusicSearchQuery)
