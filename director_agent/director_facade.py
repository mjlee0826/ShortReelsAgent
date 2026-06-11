from director_agent.context_compressor import ContextCompressor
from director_agent.states.scheduling_state import SchedulingState

class DirectorFacade:
    """
    Facade Pattern: Phase 4 總指揮。
    已升級：支援 Template DNA 導入與對話式微調 (Iterative Refinement)。
    配樂 DNA 改由上游 ``BlueprintPreparer`` 並行解析後直接傳入,不再於狀態機內現抓(``IntentState`` 退場)。
    """
    def __init__(self):
        self.compressor = ContextCompressor()

    def generate_timeline(self, user_prompt: str, raw_assets: list, template_dna: dict = None,
                          audio_dna: dict = None, previous_timeline: list = None,
                          regenerate_music: bool = True, previous_bgm_track: dict = None) -> dict:
        """
        一鍵生成或微調時間軸(純 scheduling + reflection;配樂已於上游並行解析後傳入)。
        :param user_prompt: 使用者指令
        :param raw_assets: Phase 1 產出的原始素材清單
        :param template_dna: (選填) Phase 2 產出的範本 DNA
        :param audio_dna: (選填) Phase 3 配樂 DNA,由 ``BlueprintPreparer`` 並行解析後傳入(取代原狀態機現抓)
        :param previous_timeline: (選填) 若使用者要求修改，傳入上一版的藍圖
        :param regenerate_music: 是否重新挑配樂；False 時最終藍圖沿用 previous_bgm_track
        :param previous_bgm_track: regenerate_music 為 False 時，最終藍圖直接沿用此 bgm_track
        """
        print("\n🎬 [Director Agent] 導演大腦啟動...")

        # 1. 預處理：資料降維 (排除 technical_score < 40 的素材)
        compressed_assets = self.compressor.compress(raw_assets)

        # 2. 初始化 context;audio_dna 由上游並行解析後直接注入(取代原 IntentState 現抓)
        context = {
            "user_prompt": user_prompt,
            "assets": compressed_assets,
            "template_dna": template_dna,           # 範本資訊
            "previous_timeline": previous_timeline,  # 歷史藍圖
            "regenerate_music": regenerate_music,     # False 時沿用 previous_bgm_track
            # None → {} 保持與舊 IntentState 一致(prompt 端永遠拿到 dict,不會收到 None)
            "audio_dna": audio_dna or {},             # 配樂 DNA(上游 fork-join 產出)
            "timeline_draft": None,
            "final_timeline": None
        }

        # 3. 狀態機啟動(入口改 SchedulingState;配樂節點 IntentState 已退場)
        state = SchedulingState()
        while state is not None:
            state = state.run(context)

        video_fps_list = [
            asset.get("fps", 30.0) 
            for asset in compressed_assets 
            if asset.get("type") == "video"
        ]
        
        # 找出最高的 FPS 數值
        max_fps = max(video_fps_list) if video_fps_list else 30.0
        
        # 如果最高 FPS 達到或超過高幀標準 (例如 50 以上)，則全局設定為 60，否則為 30
        target_fps = 60 if max_fps >= 50.0 else 30

        final_blueprint = {
            "global_settings": {
                "fps": target_fps,
                "aspect_ratio": "9:16"
            },
            "bgm_track": context.get("bgm_track", {"track_id": None}), # ⬅️ 新增這一行
            "timeline": context["final_timeline"]
        }

        # 不重抓配樂（純對話微調）：直接沿用上一版 bgm_track，覆蓋 LLM 可能重寫的內容，
        # 確保使用者既有的曲目 / 音量 / 起播在微調後完整保留（政策 C 的音樂保護）。
        if not regenerate_music and previous_bgm_track is not None:
            final_blueprint["bgm_track"] = previous_bgm_track

        print(f"✅ [Director Agent] 藍圖規劃完成！(自動設定全局 FPS 為: {target_fps})")
        
        # 回傳封裝好的藍圖與音訊 DNA
        return final_blueprint, context.get("audio_dna", {})