from config.director_config import DIRECTOR_TWO_STAGE_MIN_ASSETS
from director_agent.context_compressor import ContextCompressor
from director_agent.states.casting_state import CastingState
from director_agent.states.scheduling_state import SchedulingState

# ── 藍圖預設值（禁 magic number / magic string，集中具名）──────────────────────────
# 運鏡 / 卡點為純 render-time 視覺旗標，與 AI 決策無關：生成時固定給開啟預設，
# 之後完全交由前端「專案 / 輸出」面板的即時開關控制（不再透過生成參數 / 重新生成）。
DEFAULT_AUTO_MOTION = True
DEFAULT_AUTO_PUNCH = True
# 逐段運鏡預設：LLM 不輸出 motion，由後端統一補此值（前端視 'auto' 為依索引自動輪替運鏡）。
DEFAULT_CLIP_MOTION = "auto"


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
        # id → 完整 dossier 反查表:兩階段第二段按 shortlist 取選中素材的完整 metadata
        asset_index = {
            asset["id"]: asset for asset in compressed_assets if asset.get("id")
        }

        # 2. 初始化 context;audio_dna 由上游並行解析後直接注入(取代原 IntentState 現抓)
        context = {
            "user_prompt": user_prompt,
            "assets": compressed_assets,
            "asset_index": asset_index,             # 兩階段第二段取選中 dossier 用
            "template_dna": template_dna,           # 範本資訊
            "previous_timeline": previous_timeline,  # 歷史藍圖
            "regenerate_music": regenerate_music,     # False 時沿用 previous_bgm_track
            # None → {} 保持與舊 IntentState 一致(prompt 端永遠拿到 dict,不會收到 None)
            "audio_dna": audio_dna or {},             # 配樂 DNA(上游 fork-join 產出)
            "timeline_draft": None,
            "final_timeline": None
        }

        # 3. 選入口狀態:素材夠多且為全新生成 → 先 Casting 選角縮小 context(兩階段);
        #    微調(有 previous_timeline)或素材不多 → 維持單階段 SchedulingState(零回歸)。
        if len(compressed_assets) > DIRECTOR_TWO_STAGE_MIN_ASSETS and not previous_timeline:
            print(
                f"🎯 [Director Agent] 素材 {len(compressed_assets)} 個 > "
                f"{DIRECTOR_TWO_STAGE_MIN_ASSETS},啟用兩階段(Casting → Scheduling)。"
            )
            state = CastingState()
        else:
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

        # LLM 不再輸出逐段 motion（已移出 response schema）：在此對每段補預設運鏡值，
        # 讓藍圖欄位完整（SSOT）；timeline 為 list[dict]（JSON parse 而來），故直接 setdefault。
        timeline = context["final_timeline"] or []
        for clip in timeline:
            if isinstance(clip, dict):
                clip.setdefault("motion", DEFAULT_CLIP_MOTION)

        final_blueprint = {
            # 運鏡 / 卡點旗標於此初始化（與 fps / 比例同為 render-time 全域設定），
            # 取代過去由 service 層吃 enable_motion 參數寫入的做法；生成後由前端即時開關接管。
            "global_settings": {
                "fps": target_fps,
                "aspect_ratio": "9:16",
                "auto_motion": DEFAULT_AUTO_MOTION,
                "auto_punch": DEFAULT_AUTO_PUNCH,
            },
            "bgm_track": context.get("bgm_track", {"track_id": None}), # ⬅️ 新增這一行
            "timeline": timeline
        }

        # 不重抓配樂（純對話微調）：直接沿用上一版 bgm_track，覆蓋 LLM 可能重寫的內容，
        # 確保使用者既有的曲目 / 音量 / 起播在微調後完整保留（政策 C 的音樂保護）。
        if not regenerate_music and previous_bgm_track is not None:
            final_blueprint["bgm_track"] = previous_bgm_track

        print(f"✅ [Director Agent] 藍圖規劃完成！(自動設定全局 FPS 為: {target_fps})")
        
        # 回傳封裝好的藍圖與音訊 DNA
        return final_blueprint, context.get("audio_dna", {})