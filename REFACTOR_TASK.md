# 重構任務說明（給接手 agent 的完整 Prompt）

> 這份檔案是一次完整 codebase 調查後的結論，目的是讓**沒有先前對話脈絡**的 agent 能直接理解並執行。
> 請先完整讀過本檔，再開始動工。檔內標注的行號是「規劃當下」的位置，可能因改動而漂移，請以函式/語意定位為準。

---

## 0. 任務總覽

在 ShortReelsAgent（短影音素材處理 + AI 剪輯）專案上，完成兩件事：

1. **架構重構（主軸，B 方案）**：把「素材的身分標識」從**檔名（basename）**改成**相對路徑（relpath）**，並把磁碟結構分層成 `raw/`（原始）與 `standardized/`（標準化 `_std` 衍生）。
2. **解決五個既有問題**（詳見第 4 節），其中問題 4（素材計數錯亂）會被 B 方案一併解掉。

> **為什麼做 B 方案**：目前整條生成鏈（blueprint → render → 前端預覽）只認「檔名 + 單一 root URL」，render URL 一律是 `assetsRootUrl + 檔名`。若把素材分到子資料夾，檔名就無法定位到正確子目錄。B 方案把「子目錄」直接寫進素材 id（relpath），讓 `root + relpath` 直接命中磁碟，StaticFiles 原生掛載即可、不需任何「對外扁平、對內分層」的解析 workaround。這也為「未來支援 Google Drive 巢狀資料夾的素材」鋪好資料模型。

---

## 1. 強制程式碼規範（來自 CLAUDE.md，必須遵守）

- **輸出與註解一律用繁體中文。**
- 所有程式碼要 refactor，符合 design pattern。
- 每個 class / function 必須有 docstring。
- 用 dataclass 或 pydantic 定義資料結構。
- 禁止 magic number / magic string，所有常數必須命名。
- **不用寫 test file。**
- 在程式碼必要處寫註解（解釋「為什麼」，非「做什麼」）。

## 2. 環境與既有慣例（重要）

- **執行環境在遠端 Leibniz**，本機桌面只有原始碼。GPU / 套件 / 實際執行與錯誤重現都在 Leibniz；**不要預期在本機跑起後端或模型**。共用 GPU 常 OOM。
- **`project_meta.json` 一律走 `backend/services/project_meta_store.py`（ProjectMetaStore）做原子讀寫**。NFS 上嚴禁 `open('w')` 直寫，併發會造成 `Extra data` 損毀，讓 `/api/projects` 500。讀-改-寫請用 `project_meta_store.update(project_dir, mutate_fn)`（per-path 鎖）。
- **Log 慣例：目前刻意全用 `print`**，不要擅自換成 logging。tag 格式如 `[Component]`、`[Component Error]`、`[Component Warning]`。只對「失敗 / 載入 / 吞錯」加 log。
- **前端配色走 IG 中性深色**：顏色用 `frontend/src/index.css` 的 `@theme` token（如 `text-ink`、`bg-surface`、`text-accent`），**不要硬編色碼**。
- 既有版本鎖定（動到相關套件時注意，但本任務多半用不到）：torch 2.10 全家、torchaudio 2.10、torchcodec 0.10；mediapipe 用 Tasks API 並 pin 0.10.30；Qwen 量化用 bitsandbytes NF4。

## 3. 系統現況關鍵事實（先理解，能省下重新探索）

**素材資料夾現況**（單層，全擠在一起）：
```
{ASSETS_DIR}/{user_id}/{project_name}/
├─ 原始素材（clip.mov, photo.jpg, pic.heic, normal.mp4 ...）
├─ 標準化衍生（clip_std.mp4, pic_std.jpg ...）   ← 與原始檔同層（亂源）
├─ phase1_asset_status.json      （全狀態：success/rejected/error，key=檔名）
├─ phase1_assets_metadata.json   （success-only，每筆含 file + metadata）
├─ phase2_template_dna.json / phase3_audio_dna.json / phase4_blueprint.json
└─ project_meta.json
```

**素材身分目前 = basename（檔名）**，貫穿全鏈：
- `backend/services/asset_discovery.py::collect_asset_files`（素材探索單一真相）：掃 project 根目錄，**跳過「已有對應 `_std` 版本」的原始檔**，回傳絕對路徑 list。
- Phase 1 落地：`media_processor/pipeline/stages/assembly_video_stage.py:50` 存 `file=絕對路徑`；但所有讀取端都 `os.path.basename()` 化（`director_service._dump_phase1_metadata`、`asset_repository._read_metadata_map`）。
- `phase1_asset_status.json` 的 key = basename。
- `project_meta.json` 的 `asset_strategies` / `dirty_assets` / `analyzed_strategies` 的 key = basename。
- `AssetView.filename` = basename（前端素材列表/詳情/策略 API 都用它當識別）。
- blueprint `clip_id` = basename（`director_agent/context_compressor.py:36` 用 `os.path.basename(asset["file"])`）。

**生成鏈如何用素材路徑**（B 方案的核心約束）：
- `assetsRootUrl`（`backend/services/director_service.py:296`）= `{backend_url}/static/{user_id}/{folder_name}/`
- render 參數在 `backend/services/render_service.py:42-44` 組成 `{ blueprint, assetsRootUrl }`
- 前端 `frontend/src/components/RemotionPlayer/ClipComponent.jsx:8-9`：`fileUrl = assetsRootUrl + clip_id`
- 素材預覽 URL `backend/services/asset_repository.py:215`：`{backend_url}/static/{user_id}/{project}/{quote(filename)}`
- 靜態服務 `backend/main.py:54`：`app.mount("/static", StaticFiles(directory=ASSETS_DIR))`，URL 路徑逐字對應磁碟。
- **結論**：只要 blueprint 的 id 改成 relpath（如 `standardized/clip_std.mp4`），`assetsRootUrl + id` 就直接命中 `ASSETS_DIR/{user}/{project}/standardized/clip_std.mp4`，**StaticFiles 不用改、ClipComponent 不用改**。

**既有可重用機制（務必重用，不要另寫）**：
- `backend/services/asset_repository.py::select_pending`（約 250-261）：回「未處理（不在 status 檔）∪ dirty（策略變更）」的素材清單 —— 這正是「只跑新素材」需要的差集。
- `backend/api/assets.py::generate_assets`（約 144-153）：已示範正確用法 `select_pending → run_phase1(asset_filenames=..., require_success=False) → clear_dirty`。
- `director_service.run_phase1(folder_name, user_id, asset_filenames=..., asset_strategies=..., require_success=...)`：已支援「子集重分析」+ metadata/status 增量合併（merge）。
- `backend/services/project_meta_store.py`：原子讀寫 meta。

---

## 4. 工作項目

### 工作 1 — 移除 dead code：`create_project`（POST /api/projects）

**結論**：已確認是 dead code。前端 `api.service.js` 雖有 `createProject()`，但全站從不呼叫；所有建專案都走 `createProjectFromDrive()` → `POST /api/projects/from-drive`（產品定位只支援 Google Drive 來源）。

**改動**：
- `backend/api/projects.py`：刪除 `create_project` route（約 175-199）與只服務它的 `CreateProjectRequest`（約 56-60）。
- `frontend/src/services/api.service.js`：刪除 `createProject(displayName)` 方法（143-146）。
- 確認 `from-drive` 流程與 `useProjectStore`（只有 `createProjectFromDrive`，無 `createProject` action）不受影響。

---

### 工作 2 — 補「手動同步」按鈕：`sync_project`（POST /api/projects/{name}/sync）

**結論**：後端 route 已存在（`backend/api/projects.py:248-257`，回 `SyncReport`，已用 `asyncio.to_thread`），但前端零串接，同步只靠背景 poller + 建立時的首次同步。要補一顆手動觸發按鈕。

**改動**：
- 前端 `api.service.js`：新增 `syncProject(projectName)` → `POST /api/projects/{projectName}/sync`（參考既有 `deleteProject` 樣式）。
- 前端 `useProjectStore`（`frontend/src/store/useProjectStore.js`）：新增 action（如 `syncProject`），呼叫後 `await fetchProjects()` 刷新狀態；過程要有 loading / 錯誤處理（參考既有 `createProjectFromDrive` action）。
- UI 按鈕：加在專案卡片 `frontend/src/components/ProjectGrid/ProjectCard.jsx`（或專案總覽工具列）。配色走 `@theme` token。同步是阻塞操作（下載 + Phase 1，可能久），按鈕要有「同步中」狀態避免重複點擊；完成後刷新 `sync_status`（顯示邏輯在 `frontend/src/components/ProjectGrid/projectStatus.js`）。

---

### 工作 3 — 同步只重跑「新素材」的 Phase 1（增量）

**根因**：`backend/services/ingestion_provider.py:21-23` 的 `_phase1_runner` 呼叫 `director_service.run_phase1(project_name, user_id)` **不帶 `asset_filenames`** → 只要素材簽章一變（`ingestion_engine/cloud_ingestion_service.py:123-129`，整包檔名+大小 hash），就對**整個資料夾全量重跑**感知分析（Qwen/Gemini，很貴）。

**解法**（重用既有增量機制）：在 `director_service` 新增一個增量方法，並讓 runner 改呼叫它。
- 在 `backend/services/director_service.py` 新增方法（例如 `run_phase1_incremental(folder_name, user_id, tracker=None)`）：
  1. **先 `standardize`**（關鍵順序！）：新下載的 `.mov/.heic` 要先標準化成 `_std`，否則 `select_pending` 算出的是原始檔名，與 `run_phase1` 內 standardize 後的 `_std` 檔名對不上、會被過濾成空。
  2. `pending = asset_repository.select_pending(user_id, folder_name)`（此時 collect 回的是標準化後身分）。
  3. `pending` 為空 → 直接 return（無新素材，不重跑）。
  4. `run_phase1(folder_name, user_id, asset_filenames=pending, asset_strategies=get_asset_strategies(...), require_success=False)`。
  5. `asset_repository.clear_dirty(user_id, folder_name, pending)`。
- `backend/services/ingestion_provider.py::_phase1_runner` 改呼叫這個增量方法。
- `director_service` 已持有 `self.asset_repository`（建構式內），直接用。
- 首次同步時 status 檔為空 → `select_pending` 回全部 → 全量跑（正確）；之後只跑新檔。

> **注意**：本工作與工作 4（B 方案）耦合 —— `select_pending`/`collect_asset_files` 在 B 方案後回傳的是 relpath，要確保身分一致。建議**先完成工作 4 的路徑化，再做工作 3**。

---

### 工作 4（主軸）— 素材身分路徑化 + `raw/` / `standardized/` 分層（同時解掉問題 4 計數錯亂）

**目標磁碟結構**：
```
{project}/
├─ raw/            ← 所有原始下載 + 上傳（含使用者自訂音訊）
│  ├─ clip.mov / photo.jpg / pic.heic / normal.mp4 ...
├─ standardized/   ← media_standardizer 產出的 _std 衍生檔
│  ├─ clip_std.mp4 / pic_std.jpg ...
├─ phase1_asset_status.json / phase1_assets_metadata.json
├─ phase2_template_dna.json / phase3_audio_dna.json / phase4_blueprint.json
└─ project_meta.json   （JSON 全部維持在 project 根目錄）
```

**核心觀念**：素材身分 = **相對 project root 的相對路徑**（如 `raw/photo.jpg`、`standardized/clip_std.mp4`）。
為避免 magic string，建議在 `asset_discovery.py` 集中定義子目錄常數（如 `RAW_SUBDIR = "raw"`、`STANDARDIZED_SUBDIR = "standardized"`）。

**改動清單**（依資料流，由內而外）：

1. **素材探索（核心，改這裡下游全受惠）** `backend/services/asset_discovery.py::collect_asset_files`
   - 掃 `raw/` + `standardized/` 兩個子目錄。
   - 跨目錄套既有「原始檔若已有對應 `_std` 版本就跳過」規則（`raw/clip.mov` 有 `standardized/clip_std.mp4` → 跳過 `raw/clip.mov`；`raw/photo.jpg` 無對應 → 保留）。
   - 回傳「相對 project root 的 relpath」（或絕對路徑，但下游 key 一律用 relpath；二擇一並全程一致）。

2. **標準化輸出** `media_tools/media_standardizer.py::standardize_folder`
   - 掃 `raw/`、輸出 `_std` 到 `standardized/`（先 `os.makedirs(standardized, exist_ok=True)`）。
   - 呼叫端（`director_service.run_phase1` 內 `self.standardizer.standardize_folder(target_dir)`）相應調整路徑語意。

3. **雲端下載目標** `ingestion_engine/public_drive_api_adapter.py::download_folder`（約 94-100）+ `ingestion_engine/cloud_ingestion_service.py:134`
   - 下載到 `{project}/raw/`（`makedirs`）。「已存在且同大小跳過」的增量判斷改看 `raw/`。原始檔不移動 → 不會重複下載。
   - **不要**改 `list_files`/`download_folder` 去遞迴 Drive 子資料夾（見下方「範圍界線」）。

4. **Phase 1 落地身分路徑化**
   - `media_processor/pipeline/stages/assembly_video_stage.py:50`：`file` 改存 relpath（或讓 director 落地時轉 relpath）。
   - `backend/services/director_service.py::_dump_phase1_metadata` / `_dump_phase1_status`、`backend/services/asset_repository.py::_read_metadata_map` / `_read_status_map`：key 從 basename 改 relpath，且全程一致。

5. **逐檔策略 meta key 路徑化** `backend/services/asset_repository.py`
   - `asset_strategies` / `dirty_assets` / `analyzed_strategies` 的 key 改 relpath。`set_strategy` / `select_pending` / `clear_dirty` / `get_asset_strategies` 同步。

6. **AssetView 與素材 API**（前端會碰，注意 `/` 問題）
   - `AssetView`（`asset_repository.py`）：建議新增 `path`（relpath，當識別/key）並保留 `filename`（basename，純顯示）。
   - **素材詳情 / 策略 API**（`backend/api/assets.py` 的 `GET /assets/{filename}`、`PATCH /assets/{filename}/strategy`）：原本用 path param 帶檔名，relpath 含 `/` 會打架。**建議改成用 query 參數或 request body 傳 `path`**（比 `{filename:path}` + `encodeURIComponent` 的 `%2F` 坑更穩）。
   - 前端 `api.service.js::fetchAssetDetail` / `setAssetStrategy`（約 170-184）與素材頁元件（`frontend/src/components/AssetGrid/...`、`frontend/src/pages/AssetListPage.jsx`）相應改用 `path`；**畫面顯示檔名時取 basename**。

7. **媒體 URL** `backend/services/asset_repository.py:215::_build_media_url`
   - 改 `quote(relpath, safe='/')`（保留斜線），組成 `/static/{user}/{project}/{relpath}`。

8. **blueprint clip_id 路徑化** `director_agent/context_compressor.py:36`
   - id 用 relpath 取代 `os.path.basename(asset["file"])`。LLM prompt 內 asset id 隨之變 relpath。
   - 確認 `director_agent` 後續狀態（如 `states/reflection_state.py`）與 blueprint timeline 的 `clip_id` 一致用 relpath。

9. **render** — 確認**不需改 code**：`assetsRootUrl`（`director_service.py:296`）保持 `/static/{user}/{project}/`、StaticFiles（`main.py:54`）保持掛 `ASSETS_DIR`、`ClipComponent.jsx` 保持 `root + clip_id`。relpath 寫進 clip_id 後天然命中。**請實測影片 seek（HTTP Range）正常。**

10. **音訊** `backend/api/director.py:142`（上傳）+ `backend/services/director_service.py:250`（`user_music_file`）→ 指向 `raw/`。（音訊不經 standardize；最終配樂走 `/cache` 全域快取，不影響。）

11. **計數對齊（解問題 4）** `backend/api/projects.py:109-116::_count_assets` 與 `backend/services/director_service.py:44-47::_update_project_meta`
    - 改用 `collect_asset_files` 計數（去重後即真實素材數，與素材頁一致）。這正是問題 4「總覽數量把 `_std` 衍生檔也算進去、和素材頁對不上」的修正。

12. **封面** `backend/services/project_cover_service.py:51`
    - 原本 `os.path.join(project_dir, filename)` → 改用 relpath 組路徑（素材已在子目錄）；封面挑選仍讀 `phase1_assets_metadata.json`（在根目錄，不動）。

**範圍界線（避免 scope 膨脹）**：本任務只做「資料模型路徑化 + `raw`/`standardized` 分層」。**不要**現在就實作「讀取 Google Drive 巢狀子資料夾」——`list_files`/`download_folder` 維持單層（`ingestion_engine/cloud_storage_adapter.py:25` 註解寫明只列一層）。路徑式 id 已讓未來補遞迴變容易，那是後續另一個任務。

---

### 工作 5 — 退出專案後，頂部麵包屑沒更新

**根因**：`frontend/src/components/AppHeader/AppHeader.jsx:18` 讀 `useProjectStore.currentProject` 顯示麵包屑；進入專案時 `selectProject(project)` 設值，但返回首頁的 `frontend/src/pages/ProjectDashboard.jsx:26-28` 掛載時只 `fetchProjects()`，**沒清掉 `currentProject`** → 麵包屑停在舊專案。

**解法**：
- `useProjectStore`（`frontend/src/store/useProjectStore.js`）新增 `clearCurrentProject: () => set({ currentProject: null })`（參考既有 `deleteProject` 內 `set({ currentProject: null })` 的模式，約 50 行）。
- `ProjectDashboard` 在 mount 時呼叫它（在 `fetchProjects` 的 effect 內）。**注意 React hook 規則**：在元件頂層解構 `clearCurrentProject`，或用 `useProjectStore.getState().clearCurrentProject()`，不要在 effect 內呼叫 selector hook。

---

## 5. 建議執行順序

1. **工作 1（刪 dead code）+ 工作 5（麵包屑）** —— 獨立、低風險，先清掉。
2. **工作 4（B 方案路徑化 + 分層）** —— 影響面最廣的主軸。子順序：`collect_asset_files` → standardizer 輸出 → download 目標 → Phase 1 metadata/status key 路徑化 → 策略 meta key → AssetView/素材 API（含 `/` 問題）→ media_url → blueprint/context_compressor → 計數對齊 → 封面 → 確認 render 不用改並實測。
3. **工作 3（增量同步）** —— 建立在工作 4 的 relpath 身分之上。
4. **工作 2（手動同步按鈕）** —— 前端，最後做。
5. **資料遷移 + 端到端驗證**（見下）。

## 6. 既有資料遷移（⚠️ 動到使用者資料，執行前先與使用者確認方式）

現有專案的素材都在 project 根目錄，且 blueprint / metadata / status / meta 的 key 都是 basename。B 方案上線需要處理它們。三個選項（**使用者尚未拍板，預設建議第 1 個，但動手前務必確認**）：
1. **一次性 migration script**（建議）：在 Leibniz 跑一次，把每個舊專案根目錄的原始檔搬進 `raw/`、`_std` 搬進 `standardized/`，並把 blueprint/metadata/status/meta 的 basename key 重寫成 relpath。NFS 上搬檔要原子（先搬到位再切換），且走 `project_meta_store` 寫 meta。
2. **啟動時自動遷移**：讀取專案時偵測「無 `raw/` 子目錄」就地遷移。免手動，但遷移邏輯常駐 + 要處理併發讀取競態。
3. **程式碼相容新舊**：`collect_asset_files` 與身分解析同時相容「根目錄舊結構」與「raw/std 新結構」。零遷移風險，但長期兩套邏輯並存成技術債。

## 7. 驗證方式（在 Leibniz，非本機）

端到端跑一輪，逐項確認：
- 建立一個 Google Drive 來源專案 → 同步 → 磁碟出現 `raw/` + `standardized/`，JSON 仍在根目錄。
- 素材頁：素材數量正確（去重、不含 `_std` 重複）、縮圖正常、改策略 / 重新分析可用。
- **總覽頁素材數量 == 素材頁數量**（驗證問題 4 修正）。
- 生成 blueprint → 編輯器 render 預覽影片**能播放且可 seek**（驗證 relpath URL 命中 + HTTP Range/206 正常）。
- 手動同步按鈕：在 Drive **新增**一個檔 → 點同步 → log「正在處理 N 個素材」的 N 只含新檔（驗證工作 3 增量，而非全量）。
- 退出專案回首頁 → 頂部麵包屑正確消失/更新（驗證工作 5）。
- 確認 `create_project` 已移除、前端建專案（from-drive）仍正常（驗證工作 1）。

## 8. 動手前建議先讀的檔案

`backend/api/projects.py`、`backend/api/assets.py`、`backend/services/director_service.py`、`backend/services/asset_repository.py`、`backend/services/asset_discovery.py`、`backend/services/ingestion_provider.py`、`ingestion_engine/cloud_ingestion_service.py`、`ingestion_engine/public_drive_api_adapter.py`、`media_tools/media_standardizer.py`、`backend/main.py`、`director_agent/context_compressor.py`、`media_processor/pipeline/stages/assembly_video_stage.py`、`backend/services/render_service.py`；前端 `frontend/src/services/api.service.js`、`frontend/src/store/useProjectStore.js`、`frontend/src/components/AppHeader/AppHeader.jsx`、`frontend/src/pages/ProjectDashboard.jsx`、`frontend/src/components/RemotionPlayer/ClipComponent.jsx`、`frontend/src/components/ProjectGrid/`（ProjectCard、projectStatus）、`frontend/src/pages/AssetListPage.jsx`。
