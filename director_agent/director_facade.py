from config.director_config import DIRECTOR_AGENTIC_MAX_STEPS, DIRECTOR_MAX_CRITIC_RETRIES
from director_agent.agent_loop import field_manifest
from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.critic_gate import CriticGate
from director_agent.agent_loop.loop_runner import DirectorAgentLoop, build_director_registry
from director_agent.context_compressor import ContextCompressor
from model.managers.director_provider import get_director_manager

# ── 藍圖預設值（禁 magic number / magic string，集中具名）──────────────────────────
# 運鏡 / 卡點為純 render-time 視覺旗標，與 AI 決策無關：生成時固定給開啟預設，
# 之後完全交由前端「專案 / 輸出」面板的即時開關控制（不再透過生成參數 / 重新生成）。
DEFAULT_AUTO_MOTION = True
DEFAULT_AUTO_PUNCH = True
# 逐段運鏡預設：LLM 不輸出 motion，由後端統一補此值（前端視 'auto' 為依索引自動輪替運鏡）。
DEFAULT_CLIP_MOTION = "auto"
# 逐段調色預設：無 color（或舊藍圖只有 legacy filter 字串）時補此值，確保藍圖永遠帶完整 color 欄位。
DEFAULT_CLIP_COLOR = {"preset": "none"}
# 全局 FPS 判定門檻：任一影片 fps ≥ 此值 → 全局 60，否則 30。
_HIGH_FPS_THRESHOLD = 50.0


class DirectorFacade:
    """
    Facade Pattern: Phase 4 總指揮（agentic 改造後）。

    不再跑固定兩階段狀態機：改以 Claude agentic tool-use loop 驅動導演自選素材精讀（``get_fields``）、
    必讀原素材（``view_raw``）、必要時修正 metadata / 問使用者（``ask_user``），最後 ``submit_blueprint``
    交由 :class:`CriticGate` 物理驗證 + 必讀強制、有錯把錯誤餵回同一對話就地修。導演 ``ask_user`` 時 loop
    會拋 ``ClarificationRequested``（B2 暫停），由 ``director_service`` 落地 session、之後 :meth:`resume_timeline`
    續跑。本層負責驅動 loop 與藍圖後處理（全局 FPS / 逐段預設補完 / 配樂保護）。
    """

    def __init__(self):
        """持有無狀態的 ``ContextCompressor``（特徵降維 + 非破壞性過濾）。"""
        self.compressor = ContextCompressor()

    def generate_timeline(self, user_prompt: str, raw_assets: list, template_dna: dict = None,
                          previous_timeline: list = None, regenerate_music: bool = True,
                          previous_bgm_track: dict = None, tracker=None, project_dir: str = "",
                          music_future=None, audio_dna: dict = None, creative_brief: str = "") -> tuple:
        """
        一鍵生成或微調時間軸（agentic loop）。導演 ask_user 時往上拋 ``ClarificationRequested``（不在此攔）。

        配樂走兩段式：``music_future`` 為背景準備中的配樂（與 loop 重疊，導演用 get_music_beats join 取
        beats）；``audio_dna`` 為微調時已從快取載入的配樂（無 future）。回 ``(final_blueprint, 解析後 audio_dna)``。

        :param creative_brief: Stage 1 brief 的創意定錨，注入首則訊息當北極星
        :param tracker: (選填) ProgressTracker，串流導演 thinking / 工具旁白到 WS
        :param project_dir: (選填) 專案絕對路徑，供 ``view_raw`` 解析素材實體檔
        """
        print("\n🎬 [Director Agent] 導演大腦啟動（agentic loop）...")

        # 1. 預處理：資料降維 + 建 id → 完整 dossier 反查表
        compressed_assets = self.compressor.compress(raw_assets)
        asset_index = {asset["id"]: asset for asset in compressed_assets if asset.get("id")}

        # 2. 取導演 manager（Claude）與其 prompt manager，組系統提示（純心法、可快取）+ 首則 user 訊息
        #    配樂不在首則訊息（改由 get_music_beats 工具按需供，與 loop 重疊背景準備）
        manager = get_director_manager()
        prompt_manager = manager.prompt_manager
        system_prompt = prompt_manager.get_director_agentic_system_prompt(
            has_template=bool(template_dna), is_refinement=bool(previous_timeline)
        )
        catalog = field_manifest.build_catalog(compressed_assets)
        user_message = prompt_manager.build_director_agentic_user_message(
            user_prompt=user_prompt,
            catalog=catalog,
            manifest_text=field_manifest.build_manifest_text(),
            creative_brief=creative_brief,
            template_dna=template_dna,
            previous_timeline=previous_timeline,
        )

        # 3. 跑 agentic loop（get_fields / view_raw / correct_metadata / get_music_beats / ask_user / submit）
        ctx = AgentContext(
            asset_index=asset_index, project_dir=project_dir or "", tracker=tracker,
            music_future=music_future, audio_dna=audio_dna,
        )
        blueprint_draft = self._build_loop().run(system_prompt, user_message, ctx)

        # 4. 後處理組裝（全局 FPS / 逐段預設 / 配樂保護）
        final_blueprint = self._assemble_blueprint(
            compressed_assets, blueprint_draft, regenerate_music, previous_bgm_track
        )
        # 解析配樂：導演有呼叫 get_music_beats → ctx.audio_dna 已就；否則此處 join 背景 future
        resolved_audio_dna = ctx.audio_dna
        if resolved_audio_dna is None:
            resolved_audio_dna = music_future.result() if music_future is not None else {}
        return final_blueprint, resolved_audio_dna or {}

    def resume_timeline(self, resume_state: dict, answer: str, raw_assets: list,
                        regenerate_music: bool = True, previous_bgm_track: dict = None,
                        audio_dna: dict = None, tracker=None, project_dir: str = "") -> dict:
        """
        B2 續跑：以使用者答案接回暫停的 loop，回最終藍圖（dict）。導演若再次 ask_user 仍會往上拋。

        重建 ctx：重新 compress 素材 → 還原已看範圍 viewed 與 metadata 修正 corrections，使必讀強制 /
        修正狀態延續。素材 / DNA 由 ``director_service`` 從 PHASE1/3 快取重載後傳入（``audio_dna`` 設入
        ctx 供 get_music_beats 直接回；系統提示與素材目錄已在持久化的 messages 內，無須重建）。
        """
        print("\n🎬 [Director Agent] 導演大腦續跑（resume）...")
        compressed_assets = self.compressor.compress(raw_assets)
        asset_index = {asset["id"]: asset for asset in compressed_assets if asset.get("id")}
        ctx = self._restore_ctx(asset_index, project_dir, tracker, resume_state, audio_dna)

        blueprint_draft = self._build_loop().resume(resume_state, answer, ctx)
        return self._assemble_blueprint(
            compressed_assets, blueprint_draft, regenerate_music, previous_bgm_track
        )

    # ── 內部組裝 ──────────────────────────────────────────────────────────────
    def _build_loop(self) -> DirectorAgentLoop:
        """組一個導演 loop（manager / 工具 / CriticGate / 收斂上限）。"""
        return DirectorAgentLoop(
            manager=get_director_manager(),
            registry=build_director_registry(),
            critic_gate=CriticGate(),
            max_steps=DIRECTOR_AGENTIC_MAX_STEPS,
            max_critic_retries=DIRECTOR_MAX_CRITIC_RETRIES,
        )

    @staticmethod
    def _restore_ctx(asset_index: dict, project_dir: str, tracker, resume_state: dict,
                     audio_dna: dict = None) -> AgentContext:
        """從續跑狀態還原 ctx：重套 metadata 修正、還原已看範圍、設入重載的配樂（無 future）。"""
        ctx = AgentContext(
            asset_index=asset_index, project_dir=project_dir or "", tracker=tracker,
            audio_dna=audio_dna,
        )
        # 重套語意修正到重新 compress 出的 dossier（physical 欄位 correct 階段已擋，這裡只重放語意值）
        for correction in resume_state.get("corrections") or []:
            dossier = asset_index.get(correction.get("asset_id"))
            if dossier is not None and correction.get("field"):
                dossier[correction["field"]] = correction.get("after")
            ctx.corrections.append(correction)
        # 還原已看範圍（list → tuple）
        ctx.viewed = {
            aid: [tuple(rng) for rng in ranges]
            for aid, ranges in (resume_state.get("viewed") or {}).items()
        }
        return ctx

    def _assemble_blueprint(self, compressed_assets: list, blueprint_draft: dict,
                            regenerate_music: bool, previous_bgm_track: dict) -> dict:
        """
        把 loop 產出的草稿組裝成最終藍圖：全局 FPS、逐段預設補完、global_settings、配樂保護。

        （run / resume 共用；不做 Critic —— 物理驗證已在 loop 的 CriticGate 完成。）
        """
        timeline = blueprint_draft.get("timeline") or []
        bgm_track = blueprint_draft.get("bgm_track") or {"track_id": None}
        text_overlays = blueprint_draft.get("text_overlays") or []

        video_fps_list = [
            asset.get("fps", 30.0)
            for asset in compressed_assets
            if asset.get("type") == "video"
        ]
        max_fps = max(video_fps_list) if video_fps_list else 30.0
        target_fps = 60 if max_fps >= _HIGH_FPS_THRESHOLD else 30

        # LLM 不輸出逐段 motion（不在 schema 內）：補預設運鏡；調色向後相容 + 補完整。
        for clip in timeline:
            if isinstance(clip, dict):
                clip.setdefault("motion", DEFAULT_CLIP_MOTION)
                if "color" not in clip:
                    legacy_filter = clip.pop("filter", None)
                    clip["color"] = (
                        {"preset": legacy_filter} if legacy_filter else dict(DEFAULT_CLIP_COLOR)
                    )

        final_blueprint = {
            "global_settings": {
                "fps": target_fps,
                "aspect_ratio": "9:16",
                "auto_motion": DEFAULT_AUTO_MOTION,
                "auto_punch": DEFAULT_AUTO_PUNCH,
            },
            "bgm_track": bgm_track,
            "timeline": timeline,
            "text_overlays": text_overlays,
        }
        # 不重抓配樂（純對話微調）：沿用上一版 bgm_track，覆蓋 LLM 可能重寫的內容（音樂保護）。
        if not regenerate_music and previous_bgm_track is not None:
            final_blueprint["bgm_track"] = previous_bgm_track

        print(f"✅ [Director Agent] 藍圖規劃完成！(自動設定全局 FPS 為: {target_fps})")
        return final_blueprint
