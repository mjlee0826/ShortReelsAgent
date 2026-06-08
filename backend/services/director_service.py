import os
import json
from datetime import datetime, timezone
from config.app_config import ASSETS_DIR, DEFAULT_BACKEND_URL, RAW_SUBDIR, STANDARDIZED_SUBDIR, TEMP_TEMPLATES_DIR
from config.project_artifacts import (
    PHASE2_TEMPLATE_DNA_FILENAME,
    PHASE3_AUDIO_DNA_FILENAME,
    PHASE4_BLUEPRINT_FILENAME,
)
from media_processor.pipeline import PipelineRunner, ProgressTracker
from media_tools.media_standardizer import MediaStandardizer
from template_engine.template_analyzer_facade import TemplateAnalyzerFacade
from director_agent.director_facade import DirectorFacade
from backend.services.asset_repository import AssetRepository
from backend.services.stores.project_meta_store import project_meta_store
from backend.services.stores.snapshot_store import snapshot_store
from backend.utils.asset_discovery import (
    PHASE1_METADATA_FILENAME,
    PHASE1_STATUS_FILENAME,
    collect_asset_files,
    to_abs_path,
)
from backend.utils.atomic_json import atomic_write_json, read_json_tolerant
from ingestion_engine.models import (
    META_KEY_PHASE1_STATUS,
    PHASE1_STATUS_DONE,
    PHASE1_STATUS_FAILED,
    PHASE1_STATUS_PROCESSING,
    PHASE1_STATUS_SKIPPED,
)


# 素材尚未(完整)分析就嘗試生成時,run_workflow 對前端回報用的訊息(避免 magic string)
ASSETS_NOT_ANALYZED_MESSAGE = (
    "素材尚未分析完成（有未處理或策略已變更的素材），請先到素材頁完成分析再生成。"
)


class AssetsNotAnalyzedError(Exception):
    """
    生成前置條件未滿足:偵測到未處理 / 策略已變更(dirty)的素材。

    感知分析(Phase 1)已改由素材頁專屬擁有,run_workflow 不再代跑;偵測到尚未分析的素材即拋此例外,
    由 API 層轉成 409 + 機器可讀 code,讓前端只在此情境引導使用者跳轉素材頁完成分析。
    """


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
        # 素材策略 / dirty / 已分析基準的儲存庫;編輯器生成時據此沿用素材頁的逐檔策略與分析結果
        self.asset_repository = AssetRepository()
        self.backend_url = os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL)

    def _update_project_meta(self, project_dir: str, folder_name: str):
        """生成完成後更新 project_meta.json 的最後修改時間、素材數量與藍圖狀態(容錯讀取 + 原子寫入)。"""
        try:
            # 委派容錯讀取:缺檔 / 無法復原回 None,維持原本「無 meta 不強建」行為
            meta = project_meta_store.read(project_dir)
            if meta is None:
                return
            # 用 collect_asset_files 計數(已去重、不含 _std 重複),與素材頁數量一致(解問題 4)
            asset_count = len(collect_asset_files(project_dir))
            meta["last_modified"] = datetime.now(timezone.utc).isoformat()
            meta["asset_count"] = asset_count
            meta["has_blueprint"] = os.path.exists(os.path.join(project_dir, PHASE4_BLUEPRINT_FILENAME))
            # 先前依設定略過自動分析(skipped)的專案,經此次手動分析後推進為 done,
            # 讓總覽卡片不再停留在「等待分析」(其餘狀態不動,避免干擾雲端同步流程管理的 phase1_status)
            if meta.get(META_KEY_PHASE1_STATUS) == PHASE1_STATUS_SKIPPED:
                meta[META_KEY_PHASE1_STATUS] = PHASE1_STATUS_DONE
            # 原子寫回,避免與 poller / REST 請求併發寫造成 Extra data 損毀
            project_meta_store.write(project_dir, meta)
        except Exception as e:
            print(f"⚠️ [Service] 更新專案 meta 失敗: {e}")

    def _mark_phase1_status(self, target_dir: str, status: str) -> None:
        """
        原子更新 project_meta 的 phase1_status，供總覽卡片 / 素材頁顯示分析階段。

        run_phase1 是「感知分析」這個動作本身，故由它統一擁有 PROCESSING→DONE/FAILED 轉換，
        讓 reanalyze / generate / 雲端增量 / 編輯器補跑四個進入點顯示一致（解卡片不顯示「分析中」）。
        無 meta 不強建（沿用 _update_project_meta 的容錯立場；CLI 無 meta 的資料夾據此自然略過）；
        走 ProjectMetaStore.update 的交易式原子寫，與 poller / REST 併發寫不互相覆蓋。
        """
        # 先確認 meta 存在再寫，避免替 CLI / 無 meta 的資料夾憑空造出半截 meta
        if project_meta_store.read(target_dir) is None:
            return

        def _set(meta: dict) -> None:
            """就地寫入 phase1_status（其餘欄位原樣保留）。"""
            meta[META_KEY_PHASE1_STATUS] = status
        project_meta_store.update(target_dir, _set)

    def _resolve_target_dir(self, folder_name: str, user_id: str = None) -> str:
        """依是否有 user_id 決定素材資料夾路徑（user 資料隔離）。"""
        if user_id:
            return os.path.join(self.base_assets_path, user_id, folder_name)
        return os.path.join(self.base_assets_path, folder_name)

    def _require_target_dir(self, folder_name: str, user_id: str = None) -> str:
        """解析素材資料夾路徑並確認存在；不存在拋 ValueError（四個 Phase 1 / 標準化進入點共用）。"""
        target_dir = self._resolve_target_dir(folder_name, user_id)
        if not os.path.isdir(target_dir):
            raise ValueError(f"找不到素材資料夾: {target_dir}")
        return target_dir

    def _assets_root_url(self, folder_name: str, user_id: str = None) -> str:
        """組出素材靜態根 URL：依 user_id 決定是否多一層使用者隔離路徑（生成與讀回共用，避免重複）。"""
        if user_id:
            return f"{self.backend_url}/static/{user_id}/{folder_name}/"
        return f"{self.backend_url}/static/{folder_name}/"

    def _standardize(self, target_dir: str) -> None:
        """
        標準化某專案素材：掃 raw/ 原始檔，``_std`` 衍生檔輸出到 standardized/（分層，解計數錯亂）。

        idempotent（standardize_folder 對已存在的 ``_std`` 跳過），故各 Phase 1 進入點都先呼叫一次
        確保素材身分穩定；重複呼叫只是再掃一次目錄、不重轉。集中於此避免三個進入點各寫一份路徑組裝。
        """
        self.standardizer.standardize_folder(
            os.path.join(target_dir, RAW_SUBDIR),
            os.path.join(target_dir, STANDARDIZED_SUBDIR),
        )

    def run_phase1(self, folder_name: str, user_id: str = None,
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
        target_dir = self._require_target_dir(folder_name, user_id)

        # 進入感知分析即標 PROCESSING:總覽卡片 / 素材頁據此顯示「分析中」。此前的下載 / 標準化
        # (雲端) = INGESTING 由雲端狀態機負責;PROCESSING→DONE/FAILED 這段改由本方法統一擁有,
        # 讓 reanalyze / generate / 雲端增量 / 編輯器補跑四個進入點顯示一致。
        self._mark_phase1_status(target_dir, PHASE1_STATUS_PROCESSING)
        try:
            # 標準化:讓素材身分穩定(raw → standardized 分層)再收集
            self._standardize(target_dir)

            # 收集待處理素材身分(relpath,如 raw/photo.jpg);子集重分析只留指定 relpath
            asset_relpaths = collect_asset_files(target_dir)
            is_subset = asset_filenames is not None
            if is_subset:
                wanted = set(asset_filenames)
                asset_relpaths = [rel for rel in asset_relpaths if rel in wanted]
            print(f"[Service] 正在處理 {len(asset_relpaths)} 個素材...")

            # Pipeline 需絕對路徑讀檔;身分(asset_id=relpath)由 runner 依 base_dir(target_dir)還原
            asset_files = [to_abs_path(target_dir, rel) for rel in asset_relpaths]

            # 以 Pipeline 框架並行跑感知分析：asset 間並行，輸出依輸入順序、僅收 success；
            # 全域預設一律 SIMPLE，逐檔 COMPLEX（Gemini 深度索引）由 asset_strategies 覆寫；
            # status_sink 另收每個 asset（含 rejected / error）的精簡狀態供 UI 落地
            status_sink: list[dict] = []
            raw_assets_metadata = self.pipeline_runner.run(
                asset_files, target_dir, tracker=tracker,
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
        except Exception:
            # 分析中途失敗:標 FAILED 讓卡片顯示「分析失敗」,再拋回呼叫端決定後續(雲端不前進簽章供重試)
            self._mark_phase1_status(target_dir, PHASE1_STATUS_FAILED)
            raise
        # 分析完成:標 DONE(覆蓋開頭 PROCESSING),卡片轉「待生成 / 可編輯」
        self._mark_phase1_status(target_dir, PHASE1_STATUS_DONE)
        return raw_assets_metadata

    def run_phase1_incremental(self, folder_name: str, user_id: str = None,
                               tracker: ProgressTracker = None) -> list[dict]:
        """
        雲端同步用的增量 Phase 1:只對「新增 / 策略變更」的素材重跑感知分析,避免整包重跑。

        關鍵順序:**先標準化**再 select_pending —— 新下載的 .mov/.heic 須先轉成 ``_std`` 身分,
        否則 select_pending 算出的是原始檔身分,與 run_phase1 標準化後的身分對不上而被過濾成空。
        首次同步時 status 檔為空 → select_pending 回全部 → 等同全量跑(正確);之後只跑新檔。
        無 user_id(CLI / 無認證)時退回整批分析(維持相容)。
        """
        # 先標準化(注意順序):新下載的 .mov/.heic 須先轉成 _std 身分,select_pending 才不會算出
        # 原始檔身分而與 run_phase1 標準化後對不上被過濾成空(見本方法 docstring 的關鍵順序說明)
        target_dir = self._require_target_dir(folder_name, user_id)
        self._standardize(target_dir)

        # 無 user_id 無法套用逐檔策略 / per-file 狀態,退回整批分析
        if not user_id:
            return self.run_phase1(folder_name, user_id=user_id, tracker=tracker)

        # 重用既有差集機制:只挑「未處理 ∪ dirty(策略變更)」的素材身分
        pending = self.asset_repository.select_pending(user_id, folder_name)
        if not pending:
            print("[Service] 無新增 / 變更素材,略過 Phase 1 增量重跑")
            return []

        strategies = self.asset_repository.get_asset_strategies(user_id, folder_name)
        success = self.run_phase1(
            folder_name, user_id=user_id, tracker=tracker,
            asset_filenames=pending, asset_strategies=strategies, require_success=False,
        )
        # 補跑完成,推進這些素材的 dirty / 已分析基準
        self.asset_repository.clear_dirty(user_id, folder_name, pending, used_strategies=strategies)
        return success

    def standardize_project(self, folder_name: str, user_id: str = None) -> None:
        """
        只對某專案做素材標準化(raw → standardized),不跑感知分析。

        供雲端同步在「使用者關閉自動分析」時也先把 .mov/.heic 等轉成 ``_std`` 身分:讓素材身分在
        使用者進素材頁前就穩定(避免日後「開始生成」因身分漂移而漏跑 Phase 1),也讓前端能預覽
        已處理素材。刻意**不動 phase1_status**(那由雲端同步狀態機管理,此處僅標準化),只順手刷新
        總覽用的 asset_count(標準化後 raw 轉檔源被 ``_std`` 取代、去重後數量可能變動)。
        """
        target_dir = self._require_target_dir(folder_name, user_id)
        self._standardize(target_dir)

        # 原子刷新總覽計數(欄位名與 _update_project_meta 一致);只動計數,不碰 phase1_status 等欄位
        def _refresh_count(meta: dict) -> None:
            """就地刷新去重後素材數與最後變動時間(不碰其餘欄位)。"""
            meta["asset_count"] = len(collect_asset_files(target_dir))
            meta["last_modified"] = datetime.now(timezone.utc).isoformat()
        project_meta_store.update(target_dir, _refresh_count)

    def _dump_phase1_metadata(self, target_dir: str, success_assets: list[dict],
                              reprocessed_ids: set, merge: bool) -> None:
        """
        落地 success-only 感知結果（Phase 4 用）。

        全量重跑直接覆寫；子集重分析則保留未重跑的舊條目、移除本次重跑者的舊條目、append 新成功者
        （以 file 的 relpath 身分為鍵；重跑後變 rejected/error 者自然從 success 清單消失）。
        """
        dump_path = os.path.join(target_dir, PHASE1_METADATA_FILENAME)
        if merge:
            # 容錯讀既有清單(損毀 / 半寫回 []);file 與 reprocessed_ids(asset_id)同為 relpath 身分
            existing = read_json_tolerant(dump_path, [])
            kept = [e for e in existing if e.get("file", "") not in reprocessed_ids]
            merged = kept + success_assets
        else:
            merged = success_assets
        # 原子寫(唯一 temp + os.replace):併發讀者恆見完整檔;讀-改-寫已由 Phase 1 執行鎖序列化
        atomic_write_json(dump_path, merged)
        print(f"💾 [Dump] 素材特徵已儲存至 {dump_path}")

    def _dump_phase1_status(self, target_dir: str, status_entries: list[dict], merge: bool) -> None:
        """
        落地全狀態檔（UI 用，dict 以檔名為鍵，含 success / rejected / error）。

        全量重跑從頭建表（順手汰除已刪素材的舊狀態）；子集重分析則合併進既有表只更新重跑者。
        """
        dump_path = os.path.join(target_dir, PHASE1_STATUS_FILENAME)
        # 子集重分析合併既有表(容錯讀,損毀 / 半寫回空表);全量重跑從頭建表
        status_map: dict = read_json_tolerant(dump_path, {}) if merge else {}
        for entry in status_entries:
            status_map[entry["asset_id"]] = entry
        # 原子寫:併發讀者(素材頁 list_assets)恆見完整檔,不再讀到半截 JSON 而 500
        atomic_write_json(dump_path, status_map)

    def run_workflow(self, prompt: str, folder_name: str, user_id: str = None,
                    template: str = None,
                    subtitles: bool = True, filters: bool = True, old_timeline: dict = None,
                    music_strategy: str = "search_copyright",
                    user_music_file: str = None):
        """
        執行完整生成工作流（Phase 2–4）：讀取素材頁已落地的 Phase 1 感知快取，提取範本 DNA，
        呼叫導演大腦產生藍圖。感知分析（Phase 1）已改由素材頁專屬擁有，本方法不再代跑。
        """
        # 若有 user_id，素材路徑改為 assets/{user_id}/{folder_name}/，實現使用者資料隔離
        target_dir = self._require_target_dir(folder_name, user_id)
        
        # --- 定義各階段的 JSON 儲存路徑 ---
        phase1_dump_path = os.path.join(target_dir, PHASE1_METADATA_FILENAME)
        phase2_dump_path = os.path.join(target_dir, PHASE2_TEMPLATE_DNA_FILENAME)
        phase3_dump_path = os.path.join(target_dir, PHASE3_AUDIO_DNA_FILENAME)
        blueprint_dump_path = os.path.join(target_dir, PHASE4_BLUEPRINT_FILENAME)

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
            # Phase 1（感知分析）已改由素材頁專屬擁有（reanalyze / 開始生成），run_workflow 不再代跑,
            # 也不再需要與素材頁互斥的 phase1_lock。此處僅讀取素材頁已落地的 success-only 感知快取。
            # 不信任使用者已先分析:偵測「未處理 ∪ 策略已變更(dirty)」素材,有就拋 AssetsNotAnalyzedError,
            # 由 API 轉 409 讓前端跳轉素材頁。無 user_id(CLI)無法算 pending,退而僅檢查快取是否存在。
            pending = self.asset_repository.select_pending(user_id, folder_name) if user_id else []
            if os.path.exists(phase1_dump_path):
                with open(phase1_dump_path, 'r', encoding='utf-8') as f:
                    raw_assets_metadata = json.load(f)
            if pending or not raw_assets_metadata:
                raise AssetsNotAnalyzedError(ASSETS_NOT_ANALYZED_MESSAGE)

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
        # 音訊上傳落在 raw/(與其他原始素材同層,不經 standardize),故在 raw/ 下解析
        user_music_file_path = (
            os.path.join(target_dir, RAW_SUBDIR, user_music_file) if user_music_file else None
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

        return {
            "blueprint": final_blueprint,
            "audio_dna": audio_dna,
            "assets_root_url": self._assets_root_url(folder_name, user_id),
        }

    def load_blueprint(self, folder_name: str, user_id: str = None) -> dict:
        """
        讀回先前生成並落地的最終藍圖（PHASE4），供前端重新進入編輯器時自動載入。

        回傳結構與 run_workflow 對齊：{ "blueprint": ..., "assets_root_url": ... }；
        尚未生成過（或檔案半寫 / 損毀）時回傳 None，由 API 層轉 404。
        """
        target_dir = self._require_target_dir(folder_name, user_id)
        blueprint_path = os.path.join(target_dir, PHASE4_BLUEPRINT_FILENAME)
        if not os.path.exists(blueprint_path):
            return None
        # 容錯讀取：半寫 / 損毀回 None，視同尚未生成
        blueprint = read_json_tolerant(blueprint_path, None)
        if not blueprint:
            return None
        return {
            "blueprint": blueprint,
            "assets_root_url": self._assets_root_url(folder_name, user_id),
        }

    # ── 編輯器具名快照（版本檢查點）：解析專案路徑後委派 snapshot_store ──────────────

    def list_snapshots(self, folder_name: str, user_id: str = None) -> list:
        """列出專案的所有快照 meta（不含 blueprint，供左欄版本清單）。"""
        target_dir = self._require_target_dir(folder_name, user_id)
        return snapshot_store.list_meta(target_dir)

    def save_snapshot(self, folder_name: str, label: str, blueprint: dict, user_id: str = None) -> dict:
        """把前端傳入的當前 blueprint 存成一筆具名快照，回傳新快照 meta。"""
        target_dir = self._require_target_dir(folder_name, user_id)
        return snapshot_store.add(target_dir, label, blueprint)

    def get_snapshot(self, folder_name: str, snapshot_id: str, user_id: str = None) -> dict:
        """以 id 取回快照供還原，回傳 { blueprint, assets_root_url }；不存在回 None。"""
        target_dir = self._require_target_dir(folder_name, user_id)
        snapshot = snapshot_store.get(target_dir, snapshot_id)
        if snapshot is None:
            return None
        return {
            "blueprint": snapshot.get("blueprint"),
            "assets_root_url": self._assets_root_url(folder_name, user_id),
        }

    def delete_snapshot(self, folder_name: str, snapshot_id: str, user_id: str = None) -> bool:
        """刪除指定快照；有刪到回 True，找不到回 False。"""
        target_dir = self._require_target_dir(folder_name, user_id)
        return snapshot_store.delete(target_dir, snapshot_id)


# 模組級單例:跨 api 端點與 ingestion_provider 共享同一份 PipelineRunner / 模型池
# (下放到本模組,讓 api → services 維持單向依賴;呼叫端一律 import 此單例,勿自行再 new)
director_service = DirectorService()