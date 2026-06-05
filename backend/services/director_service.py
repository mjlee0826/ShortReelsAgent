import os
import json
from datetime import datetime, timezone
from config.app_config import ASSETS_DIR, TEMP_TEMPLATES_DIR
from media_processor.video_strategy import VideoStrategy
from media_processor.pipeline import PipelineRunner, ProgressTracker
from media_tools.media_standardizer import MediaStandardizer
from template_engine.template_analyzer_facade import TemplateAnalyzerFacade
from director_agent.director_facade import DirectorFacade
from backend.services.asset_discovery import PHASE1_STATUS_FILENAME, collect_asset_files
from backend.services.project_meta_store import project_meta_store

# 計算素材數量時認定的媒體副檔名
_MEDIA_EXTENSIONS = {'.mp4', '.mov', '.jpg', '.jpeg', '.png', '.heic', '.heif', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}

# success-only 感知結果落地檔（供 Phase 4 使用，與全狀態的 PHASE1_STATUS_FILENAME 區分）
_PHASE1_METADATA_FILENAME = "phase1_assets_metadata.json"

# 前端影片品質選項：'1' 代表高品質（Gemini 深度索引），其餘為快速本地 Qwen 分析
_COMPLEX_VIDEO_OPTION = "1"

class DirectorService:
    """
    Service Pattern: 負責協調整個 AI 剪輯流水線 (Pipeline)
    """
    def __init__(self):
        self.base_assets_path = ASSETS_DIR
        self.standardizer = MediaStandardizer()
        # Phase 1 感知分析的並行流水線 Facade（Week 2a 取代原序列迴圈）
        self.pipeline_runner = PipelineRunner()
        self.template_analyzer = TemplateAnalyzerFacade()
        self.director = DirectorFacade()
        self.backend_url = os.getenv("BACKEND_URL", "http://localhost:5174")

    def _update_project_meta(self, project_dir: str, folder_name: str):
        """生成完成後更新 project_meta.json 的最後修改時間、素材數量與藍圖狀態(容錯讀取 + 原子寫入)。"""
        try:
            # 委派容錯讀取:缺檔 / 無法復原回 None,維持原本「無 meta 不強建」行為
            meta = project_meta_store.read(project_dir)
            if meta is None:
                return
            asset_count = sum(
                1 for fname in os.listdir(project_dir)
                if os.path.splitext(fname)[1].lower() in _MEDIA_EXTENSIONS
            )
            meta["last_modified"] = datetime.now(timezone.utc).isoformat()
            meta["asset_count"] = asset_count
            meta["has_blueprint"] = os.path.exists(os.path.join(project_dir, "phase4_blueprint.json"))
            # 原子寫回,避免與 poller / REST 請求併發寫造成 Extra data 損毀
            project_meta_store.write(project_dir, meta)
        except Exception as e:
            print(f"⚠️ [Service] 更新專案 meta 失敗: {e}")

    def _resolve_target_dir(self, folder_name: str, user_id: str = None) -> str:
        """依是否有 user_id 決定素材資料夾路徑（user 資料隔離）。"""
        if user_id:
            return os.path.join(self.base_assets_path, user_id, folder_name)
        return os.path.join(self.base_assets_path, folder_name)

    def run_phase1(self, folder_name: str, user_id: str = None,
                   video_strategy: str = "2",
                   tracker: ProgressTracker = None,
                   asset_filenames: list[str] = None,
                   asset_strategies: dict = None,
                   require_success: bool = True) -> list[dict]:
        """
        只執行 Phase 1（per-asset 感知分析）：標準化 → 收集素材 → 並行 Pipeline → 落地 metadata。

        供多種呼叫端共用：run_workflow 完整流程、雲端攝取背景預跑，以及素材頁的重新分析 / 開始生成。

        Args:
            asset_filenames: 只重跑這些檔名（子集重分析）；None 代表全部素材。
            asset_strategies: 逐檔策略覆寫 ``{檔名: "simple"|"complex"}``，透傳給 Pipeline。
            require_success: 為 True 且全部失敗時拋例外（完整生成需 ≥1 success）；
                             子集重分析設 False（重跑單張被 reject 的素材是合法情境）。

        回傳 success-only 的 raw_assets_metadata 列表。
        """
        target_dir = self._resolve_target_dir(folder_name, user_id)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")

        self.standardizer.standardize_folder(target_dir)

        # 前端影片品質選項轉策略列舉；工廠依副檔名路由，圖片一律走 SIMPLE，僅影片套用此值
        video_strategy_enum = (
            VideoStrategy.COMPLEX if video_strategy == _COMPLEX_VIDEO_OPTION
            else VideoStrategy.SIMPLE
        )

        # 收集待處理素材（沿用跳過 _std 重複 + 副檔名白名單邏輯）；子集重分析只留指定檔名
        asset_files = collect_asset_files(target_dir)
        is_subset = asset_filenames is not None
        if is_subset:
            wanted = set(asset_filenames)
            asset_files = [p for p in asset_files if os.path.basename(p) in wanted]
        print(f"[Service] 正在處理 {len(asset_files)} 個素材...")

        # 以 Pipeline 框架並行跑感知分析：asset 間並行，輸出依輸入順序、僅收 success；
        # status_sink 另收每個 asset（含 rejected / error）的精簡狀態供 UI 落地
        status_sink: list[dict] = []
        raw_assets_metadata = self.pipeline_runner.run(
            asset_files, target_dir, video_strategy_enum, tracker=tracker,
            asset_strategies=asset_strategies, status_sink=status_sink,
        )
        if require_success and not raw_assets_metadata:
            raise ValueError("資料夾內沒有成功解析的有效素材！")

        # 本次實際重跑到的檔名（子集合併時用來移除舊條目）
        reprocessed_ids = {entry["asset_id"] for entry in status_sink}
        self._dump_phase1_metadata(target_dir, raw_assets_metadata, reprocessed_ids, merge=is_subset)
        self._dump_phase1_status(target_dir, status_sink, merge=is_subset)

        # 更新專案 meta 的素材數量／最後修改時間（雲端預跑時讓專案列表即時反映）
        self._update_project_meta(target_dir, folder_name)
        return raw_assets_metadata

    def _dump_phase1_metadata(self, target_dir: str, success_assets: list[dict],
                              reprocessed_ids: set, merge: bool) -> None:
        """
        落地 success-only 感知結果（Phase 4 用）。

        全量重跑直接覆寫；子集重分析則保留未重跑的舊條目、移除本次重跑者的舊條目、append 新成功者
        （以 file 的 basename 為鍵；重跑後變 rejected/error 者自然從 success 清單消失）。
        """
        dump_path = os.path.join(target_dir, _PHASE1_METADATA_FILENAME)
        if merge and os.path.exists(dump_path):
            with open(dump_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            kept = [e for e in existing if os.path.basename(e.get("file", "")) not in reprocessed_ids]
            merged = kept + success_assets
        else:
            merged = success_assets
        with open(dump_path, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
            print(f"💾 [Dump] 素材特徵已儲存至 {dump_path}")

    def _dump_phase1_status(self, target_dir: str, status_entries: list[dict], merge: bool) -> None:
        """
        落地全狀態檔（UI 用，dict 以檔名為鍵，含 success / rejected / error）。

        全量重跑從頭建表（順手汰除已刪素材的舊狀態）；子集重分析則合併進既有表只更新重跑者。
        """
        dump_path = os.path.join(target_dir, PHASE1_STATUS_FILENAME)
        status_map: dict = {}
        if merge and os.path.exists(dump_path):
            with open(dump_path, 'r', encoding='utf-8') as f:
                status_map = json.load(f)
        for entry in status_entries:
            status_map[entry["asset_id"]] = entry
        with open(dump_path, 'w', encoding='utf-8') as f:
            json.dump(status_map, f, ensure_ascii=False, indent=2)

    def run_workflow(self, prompt: str, folder_name: str, user_id: str = None,
                    template: str = None,
                    subtitles: bool = True, filters: bool = True, old_timeline: dict = None,
                    video_strategy: str = "2", music_strategy: str = "search_copyright",
                    user_music_file: str = None,
                    tracker: ProgressTracker = None):
        """執行完整生成工作流；tracker 非 None 時把 Phase 1 進度事件廣播給其訂閱者（WebSocket）。"""
        # 若有 user_id，素材路徑改為 assets/{user_id}/{folder_name}/，實現使用者資料隔離
        target_dir = self._resolve_target_dir(folder_name, user_id)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")
        
        # --- 定義各階段的 JSON 儲存路徑 ---
        phase1_dump_path = os.path.join(target_dir, "phase1_assets_metadata.json")
        phase2_dump_path = os.path.join(target_dir, "phase2_template_dna.json")
        phase3_dump_path = os.path.join(target_dir, "phase3_audio_dna.json") # 【新增】Phase 3 存檔路徑
        blueprint_dump_path = os.path.join(target_dir, "phase4_blueprint.json")

        raw_assets_metadata = []
        template_dna = None
        audio_dna = None # 【新增】預設為 None
        
        is_refinement = old_timeline is not None

        # --- 【修改】如果是微調，連同 Phase 3 一起讀取 ---
        if is_refinement and os.path.exists(phase1_dump_path):
            print(f"[Service] 🎯 偵測到微調模式 (Refinement)，跳過耗時感知，載入本地素材快取...")
            with open(phase1_dump_path, 'r', encoding='utf-8') as f:
                raw_assets_metadata = json.load(f)
            
            if template and os.path.exists(phase2_dump_path):
                print(f"[Service] 🎯 載入本地範本 DNA 快取...")
                with open(phase2_dump_path, 'r', encoding='utf-8') as f:
                    template_dna = json.load(f)
                    
            # 【新增】載入 Phase 3 的配樂 DNA
            if os.path.exists(phase3_dump_path):
                print(f"[Service] 🎯 載入本地配樂 DNA (Phase 3) 快取...")
                with open(phase3_dump_path, 'r', encoding='utf-8') as f:
                    audio_dna = json.load(f)
        
        # --- 否則，執行完整的新生成流程 ---
        else:
            # Phase 1：per-asset 感知分析（抽成獨立方法，與雲端攝取背景預跑共用）
            raw_assets_metadata = self.run_phase1(
                folder_name, user_id=user_id, video_strategy=video_strategy, tracker=tracker
            )

            if template:
                print(f"[Service] 正在提取範本 DNA: {template}")
                template_dna = self.template_analyzer.extract_dna(template)
                
                with open(phase2_dump_path, 'w', encoding='utf-8') as f:
                    json.dump(template_dna, f, ensure_ascii=False, indent=2)
                    print(f"💾 [Dump] 範本 DNA 已儲存至 {phase2_dump_path}")

        enhanced_prompt = prompt
        if not subtitles:
            enhanced_prompt += " (注意：本影片不需要任何字幕，請讓 overlay_text 保持為空)"
        if not filters:
            enhanced_prompt += " (注意：請不要套用任何濾鏡，filter 欄位請設為 none)"

        # --- 5. Phase 4: 導演大腦 (Director Agent) ---
        print("[Service] 正在呼叫導演大腦生成藍圖...")

        # 若用戶指定了自訂音樂檔案，轉換為完整絕對路徑，供 IntentState 直接存取
        user_music_file_path = (
            os.path.join(target_dir, user_music_file) if user_music_file else None
        )

        final_blueprint, new_audio_dna = self.director.generate_timeline(
            user_prompt=enhanced_prompt,
            raw_assets=raw_assets_metadata,
            template_dna=template_dna,
            previous_timeline=old_timeline,
            user_music_file=user_music_file_path,
            music_strategy=music_strategy,
        )

        # 【新增】如果大腦有去抓新的音樂 (new_audio_dna 有值)，就覆寫舊的並 Dump 存檔
        if new_audio_dna:
            audio_dna = new_audio_dna
            with open(phase3_dump_path, 'w', encoding='utf-8') as f:
                json.dump(audio_dna, f, ensure_ascii=False, indent=2)
                print(f"💾 [Dump] 配樂 DNA 已更新並儲存至 {phase3_dump_path}")

        # --- 6. 全域快取池：轉換為獨立 URL ---
        if audio_dna and isinstance(audio_dna, dict):
            source_audio_path = audio_dna.get("local_path", {}).get("standard", "")
            
            if source_audio_path and os.path.exists(source_audio_path):
                try:
                    rel_path = os.path.relpath(source_audio_path, TEMP_TEMPLATES_DIR)
                    audio_url = f"{self.backend_url}/cache/{rel_path}".replace('\\', '/')
                    
                    if "bgm_track" in final_blueprint and isinstance(final_blueprint["bgm_track"], dict):
                        final_blueprint["bgm_track"]["track_id"] = audio_url
                        
                    print(f"🎵 [Service] 已套用全域快取配樂連結: {audio_url}")
                except Exception as e:
                    print(f"⚠️ [Service] 轉換快取連結失敗: {e}")
            else:
                print(f"⚠️ [Service] 找不到實體配樂檔案: {source_audio_path}")
        
        with open(blueprint_dump_path, 'w', encoding='utf-8') as f:
            json.dump(final_blueprint, f, ensure_ascii=False, indent=2)
            print(f"💾 [Dump] 最終劇本藍圖已儲存至 {blueprint_dump_path}")

        # 更新專案 meta（最後修改時間、素材數量、藍圖狀態）
        self._update_project_meta(target_dir, folder_name)

        # 回傳 assets_root_url 依 user_id 決定路徑層級
        if user_id:
            assets_root_url = f"{self.backend_url}/static/{user_id}/{folder_name}/"
        else:
            assets_root_url = f"{self.backend_url}/static/{folder_name}/"

        return {
            "blueprint": final_blueprint,
            "audio_dna": audio_dna,
            "assets_root_url": assets_root_url,
        }