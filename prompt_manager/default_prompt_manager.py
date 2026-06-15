import json

from config.color_presets import color_vocabulary_text
from config.media_processor_config import SUBJECT_CANDIDATE_TOP_N
from prompt_manager.base_prompt_manager import BasePromptManager, PromptSpec
from prompt_manager.schemas import (
    BasicMediaSemantics,
    MusicBrief,
    MusicSearchQuery,
    TemplateAnalysisSemantics,
    VideoEventIndexSemantics,
    schema_to_text,
)
from prompt_manager.preference_few_shot import build_few_shot_block


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

    def get_music_brief_prompt(self, user_prompt: str, asset_mood_summary: str = "") -> PromptSpec:
        """
        Stage 1 創意 brief（Claude）：一次給『配樂搜尋詞 + 創意定錨』。

        search_query 規則同音樂搜尋；creative_brief 是一小段給導演的創意北極星（情緒 / 風格 / 節奏感 /
        開場 hook 方向），由導演首則訊息注入，讓選曲與剪輯同調。
        """
        text = (
            "# 角色\n"
            "你同時是短影音的『配樂總監』與『創意總監』。依使用者指令與素材整體氛圍，一次給出兩樣東西：\n\n"
            "# 1. 配樂搜尋詞 search_query\n"
            "- 指名歌手 / 歌曲 → 直接「歌手 歌名」（如 \"周杰倫 稻香\"）。\n"
            "- 描述情緒 / 氛圍 / 風格 → 英文音樂關鍵字（如 \"epic cinematic trailer\"、\"funny goofy upbeat\"）。\n"
            "- 完全沒提配樂 → 依素材整體氛圍推測。\n\n"
            "# 2. 創意定錨 creative_brief\n"
            "一小段（2~4 句）定調整支片的『整體情緒 / 視覺風格 / 節奏感 / 開場 hook 方向』，當導演剪輯的北極星。\n"
            "聚焦『感覺與方向』，不要列具體片段或時間軸（那是導演的事）。\n\n"
            f"# 使用者需求\n『{user_prompt}』\n\n"
            f"# 素材整體氛圍\n{asset_mood_summary or '（無）'}\n"
        )
        return PromptSpec(text=text, schema=MusicBrief)

    # ── Agentic 導演（Phase 4 改造：多輪 tool-use loop） ─────────────────────────────
    def get_director_agentic_system_prompt(
        self, has_template: bool = False, is_refinement: bool = False
    ) -> str:
        """
        Agentic 導演的系統提示（穩定、可快取）：角色 + 工作方式（tool-use 漏斗 + 必讀強制）+ 剪輯 /
        字幕心法（含 Hook 文案框架）+ 視覺工具箱 + 配樂守則 + 物理鐵律。

        動態素材 / DNA 由首則 user 訊息注入（見 :meth:`build_director_agentic_user_message`），故本文
        純心法、可跨請求快取。偏好 few-shot（穩定）一併放在系統提示尾端。
        """
        system = (
            "# 角色\n"
            "你是具備藝術直覺的 AI 電影導演與 Remotion 渲染架構師。你面對一櫃素材，要編排出一份具電影感、\n"
            "卡得住音樂、混音合理的 9:16 直式短影音剪輯藍圖，最終以 submit_blueprint 提交、驅動 Remotion 渲染。\n\n"
            "# 最高指導原則\n"
            "【User Overrides Everything】使用者指令是絕對最高準則。要求特定風格（搞笑 / 悲傷 / 快節奏 / 畫中畫）時，\n"
            "必須蓋過素材或音樂原本的氛圍來滿足使用者。\n\n"
            "# 工作方式（你是 agentic 導演，分階段自己讀素材）\n"
            "你不會一開始就拿到所有 metadata：上層只有『極輕目錄』(每素材僅 id / type / 一行摘要)。請走漏斗：\n"
            "1. 先掃目錄摘要，鎖定一批『有機會用到』的候選素材。\n"
            "2. 用 get_fields 對候選『按需深讀』需要的欄位（依欄位 manifest 的「何時該讀」決定取哪些；別整庫狂拉）。\n"
            "3. 用 view_raw 親眼看『你打算實際放進成片』的素材片段（影片給時間點抓幀、圖片看整張）。\n"
            "4. 若畫面與 metadata 不符，用 correct_metadata 修正『語意欄位』（描述 / 情緒 / 標籤 / 主體）。\n"
            "5. 全部確認後才 submit_blueprint。\n"
            "【必讀鐵律】任何要放進成片的素材，submit 前你『必須』先用 view_raw 親眼看過它對應的片段；未親看就用會被\n"
            "系統打回。metadata 可能有誤——眼見為憑才能避免用錯素材。\n"
            "【修正邊界】correct_metadata 只能改語意欄位；時長 dur / fps / 尺寸 / 來源邊界等物理欄位以實際檔案為準、不可改。\n"
            "【節制】只對候選 / 要用的素材深讀與看圖，避免無謂成本。\n\n"
            "# 剪輯心法\n"
            "1. 選材：優先 aes（美學）/ tech（畫質）高的素材；低分留補位或捨棄。\n"
            "2. 開場 Hook：前 3 秒放最強、對比最大的素材——短影音前 3 秒留不住人就流失。\n"
            "3. 節奏 (ASL)：高能段短鏡頭快切堆張力，抒情段長鏡頭沉澱；要延長動作優先用 playback_rate 變速對齊音樂，別把連續畫面切碎。\n"
            "4. 卡點：決定剪輯點前先呼叫 get_music_beats() 取得 beats（重拍）/ onsets（起音）/ bpm，剪輯點盡量對齊；配樂可能為 none 則不需卡點。\n"
            "5. 情緒弧線：用 mood 編排起落（calm→energetic→dramatic→payoff），別平鋪。\n"
            "6. 多樣性：用 scene_tags / actions 確保相鄰片段場景或動作有變化。\n"
            "7. 混音 (Ducking)：有人聲對話（transcript / events.audio_layer）保留原音（clip_volume 高）並壓低該段 BGM（bgm_volume 低），\n"
            "   用 transcript.chunks 時間戳對齊講話時段；純風景 / 無意義環境音則原片靜音（clip_volume=0）、讓 BGM 主導。\n"
            "8. 裁切定位：依 bbox（{x1,y1,x2,y2}，0–100）算 object_position 取中心點「((x1+x2)/2)% ((y1+y2)/2)%」，\n"
            "   嚴禁無腦填 '50% 50%'；使用者意圖指向另一主體時改用 subjects 候選 bbox；crop 為 not_recommended 時優先縮放或跳過。\n\n"
            "# 字幕心法 + Hook 文案框架\n"
            "1. 以『對白字幕』為主幹：跟著人聲走、用 transcript.chunks 時間戳對齊，整支沿用一致樣式（建議 white + outline_shadow、\n"
            "   animation=fade、水平置中）。\n"
            "2. 開場 Hook 句套用經實證的鉤子公式（擇一）：打斷預期(Pattern Interrupt) / 提問 / 大膽宣稱 / 第一人稱 POV / 數據或權威；\n"
            "   前 3 秒疊一句勾子點破主題 / 製造好奇，收尾即收。\n"
            "3. 廣告 / 推廣類內容用 Hook→Problem→Solution→Proof→CTA 的敘事骨架編排素材順序與字幕。\n"
            "4. 斷句鐵律：一條字幕只放『一口氣、一個重點』，寧短勿長；逐字稿過長沿語意拆成連續多條接力顯示。\n"
            "5. 計時：每條至少約 1 秒、越長給越久；可橫跨多個片段，不必對齊片段邊界。\n"
            "6. 位置避主體：vertical / horizontal（0~100）依主體 bbox 放在不擋主體處；對白慣例壓下三分之一（vertical≈85）、水平置中。\n"
            "7. 別過度字幕 / 別堆花字：純風景 / 無人聲段留白；accent/yellow 只點在要強調的字眼。無字幕需求時 text_overlays 給 []。\n\n"
            "# 視覺工具箱（僅列前端真正支援的能力）\n"
            "- transition_in：硬切 'none'；情緒 / 場景落差大用 'fade'。\n"
            "- color：先為整支挑一個 preset 當統一基調，需要時覆寫個別 primitive；用不到的 primitive 直接省略、不要輸出 null。可用值：\n"
            f"{color_vocabulary_text()}\n"
            "- scale：可放大（1.1~1.2）做構圖微調（靜態縮放，非動態推鏡）。\n"
            "- pip_video：需畫中畫時疊加，position 僅 'top_right' / 'bottom_left'。\n"
            "- reason：每個片段先在 reason 寫下導演決策考量（選材 / 轉場 / 變速 / 混音），再填其餘參數。\n\n"
            "# 配樂\n"
            "- bgm_track 的實際音檔由系統依【配樂 DNA】注入，你不要填 track_id；只決定 start_at（通常 0.0）/ source_start / volume。\n"
            "- 【範本 DNA】的配樂僅供風格參考，不是可播放音檔，勿當 BGM。\n\n"
            "# 物理鐵律（submit 後 Critic 會驗，違反會被打回讓你就地修）\n"
            "- 時間軸嚴格首尾相接、零間隙零重疊：前一段 end_at == 下一段 start_at。\n"
            "- 變速一致性：(source_end - source_start) / playback_rate == (end_at - start_at)。\n"
            "- source_end 不得超過該素材原始長度 dur（不確定就先 get_fields 讀 dur）。\n"
            "- 嚴禁假剪輯：不可把同一支影片的連續畫面硬切成多段（相鄰片段 clip_id 必須不同）；要連續播放就合併成一個長片段。\n"
            "- clip_id 必須與目錄某筆 id 逐字完全相同：原樣照抄（含 raw/ 或 standardized/ 前綴與 _std 後綴），嚴禁改寫 / 去前綴 / 簡化 / 自拼路徑。\n"
        )
        if is_refinement:
            system += (
                "\n# 微調模式\n"
                "首則訊息附【上一版藍圖】：只針對使用者最新指令做局部修改，未提及的部分保留原樣；改動到的素材一樣要先 view_raw 確認。\n"
            )
        if has_template:
            system += (
                "\n# 範本風格參考\n"
                "參考範本的視覺氛圍與節奏步調（不需逐秒對齊其物理切點）；含 music_dna 時用它校準情緒弧線與卡點感，實際 BGM 仍以【配樂 DNA】為準。\n"
            )
        # 偏好 few-shot（穩定、可快取；策展檔缺 / 空時回空字串，零行為變動）
        few_shot = build_few_shot_block()
        if few_shot:
            system += "\n" + few_shot
        return system

    def build_director_agentic_user_message(
        self, user_prompt, catalog, manifest_text, creative_brief="",
        template_dna=None, previous_timeline=None,
    ) -> str:
        """組 agentic 導演的首則 user 訊息：使用者指令 + 創意定錨 + 極輕素材目錄 + 欄位 manifest + 範本 DNA。

        配樂不在首則訊息（改由 get_music_beats 工具按需供應，與 loop 重疊背景準備）。
        """
        msg = (
            "# 任務\n"
            "- 目標平台: Instagram Reels / TikTok (9:16)\n"
            f"- 使用者指令: {user_prompt}\n"
        )
        if creative_brief:
            msg += (
                "\n# 創意定錨（配樂 / 創意總監給的整體方向，當北極星；使用者指令仍最高優先）\n"
                f"{creative_brief}\n"
            )
        msg += (
            "\n# 素材目錄（極輕：id / type / summary 摘要；其餘欄位用 get_fields 按需取）\n"
            f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
            "# 欄位 manifest（get_fields 可取的欄位 + 何時該讀）\n"
            f"{manifest_text}\n\n"
            "# 配樂\n"
            "配樂正在背景準備中。決定剪輯點 / 卡點前，先呼叫 get_music_beats() 取得 beats / onsets / bpm"
            "（會等配樂備妥；配樂可能為 none，則不需卡點）。\n"
        )
        if template_dna:
            msg += f"\n# 範本 DNA\n{json.dumps(template_dna, ensure_ascii=False)}\n"
        if previous_timeline:
            msg += f"\n# 上一版藍圖（微調用）\n{json.dumps(previous_timeline, ensure_ascii=False)}\n"
        msg += (
            "\n請開始：先掃目錄摘要鎖定候選 → get_fields 深讀關鍵欄位 → view_raw 親眼看你要用的素材片段 → "
            "（必要時 correct_metadata 修正、卡點前 get_music_beats）→ 確認後 submit_blueprint。"
        )
        return msg
