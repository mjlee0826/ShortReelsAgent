# 分階段計時、分階段成本統計、與分任務選模型：設計文件

> 本文件規劃三件互相關聯的事：
> 1. **計時**：讓後端輸出 Phase 4（生成腳本）耗時，以及 Phase 2+3+4 的整體耗時。
> 2. **成本**：分開統計 Phase 1 / 2 / 3 / 4 各自花了多少「真實金額」（依 token 用量 × 官方單價推估）。
> 3. **選模型**：把目前「一個 default + 一個 strong」兩槽，改成**每個任務各自指定模型**，並套用新的模型對照表。
>
> 三者共用同一條落地管線（job result dict + print），且「選模型」會改變「成本」的定價表，故合併設計。
> 本文件描述設計背景與取捨。**實作已完成（2026-06-12）**；實作時對「成本歸屬」做了兩點精簡，**以實作為準**：
> ① Phase 由呼叫點的 `TaskMode` 直接推導（`usage_ledger.TASKMODE_TO_PHASE`），**不用 `phase_scope`**，只有「帳本」走 contextvar；
> ② 跨緒 `copy_context` 傳播為**三處**（`resource_executor`、`hybrid_scheduler`、外加 `blueprint_preparer`——少了第三處，Phase 2/3 金額會記不到）。
> 與 `blueprint_prep_design.md`（Phase 2∥3 fork-join）、pipeline 的 `runner.py` 配套。

---

## 1. 背景與現況盤點

### 1.1 四個 Phase 與唯一的付費來源

| Phase | 工作 | 進入點 | TaskMode | 付費？ |
|---|---|---|---|---|
| 1 | 逐素材感知分析（獨立 job，素材頁觸發） | `director_service.run_phase1` (`director_service.py:158`) | 見下 | 僅 COMPLEX 走 Gemini；SIMPLE 走本地 Qwen = $0 |
| 2 | Template DNA | `TemplateDnaProducer.produce` (`template_dna_producer.py:39`) | `TEMPLATE_ANALYSIS` | 是 |
| 3 | Music DNA | `MusicDnaProducer.produce` → `MusicDirector` (`music_director.py`) | `MUSIC_SEARCH_QUERY` | 是 |
| 4 | 導演大腦生腳本 | `DirectorFacade.generate_timeline` (`director_facade.py:13`) | `DIRECTOR_BLUEPRINT` | 是 |

Phase 1 內部依素材策略再分：

| 子任務 | TaskMode | 引擎 | 付費？ |
|---|---|---|---|
| 1a SIMPLE | `BASIC_MEDIA_ANALYSIS` | 本地 Qwen3-VL | $0 |
| 1b COMPLEX 圖片 | `DEEP_IMAGE_ANALYSIS` | Gemini | 是 |
| 1c COMPLEX 影片 | `VIDEO_EVENT_INDEX` | Gemini | 是 |

**關鍵事實**：全系統唯一會產生 API 金額的就是 **Gemini**（Qwen/Whisper/MusiQ 等為本地 GPU、Jamendo 免費）。所以「真實金額」= 每次 Gemini 呼叫的 token 用量 × 官方單價，逐 Phase 加總。

### 1.2 Gemini 呼叫的所有出口（成本記錄要攔的點）

| # | 位置 | SDK 呼叫 | 服務的 Phase |
|---|---|---|---|
| A | `gemini_model_manager.py:128` `_generate_inline` | `client.models.generate_content` | 1b / 1c（小檔）/ 2 |
| B | `gemini_model_manager.py:162` `_analyze_via_file_api` | `client.models.generate_content` | 1c / 2（大檔影片） |
| C | `gemini_model_manager.py:192` `generate_director_plan` | `chat.send_message` | 4 |
| D | `music_director.py:85` `_extract_search_query` | `client.models.generate_content`（**繞過 manager 直接打 client**） | 3 |

D 是個封裝破口：它沒走 manager 方法，直接用 `gemini.client`。成本記錄會順手把它收斂回 manager（見 §4.6）。

### 1.3 現況模型設定（兩槽）

```python
# config/model_config.py:99-100
GEMINI_DEFAULT_MODEL = 'gemini-2.5-flash'        # 服務 1b / 1c / 2 / 3
GEMINI_STRONG_MODEL  = 'gemini-3.1-pro-preview'  # 服務 4
```

`analyze_media`（1b/1c/2）與 music（3）都用 `default_model`；`generate_director_plan`（4）用 `strong_model`。**兩槽無法分任務指定**，這是 §5 要解的結構問題。

---

## 2. 需求一：Phase 計時輸出

### 2.1 要輸出的數字

在 `run_workflow`（`director_service.py:339`）量三個 wall-clock：

| 指標 | 量測範圍 | 程式位置 |
|---|---|---|
| `t_prep`（Phase 2∥3） | `blueprint_preparer.prepare()` 前後 | 已有雛形 `director_service.py:412-414` |
| `t_phase4`（Phase 4 生成腳本） | `self.director.generate_timeline(...)` 前後 | `director_service.py:430` |
| `t_phase234`（Phase 2+3+4 總耗時） | `prep_start` → `generate_timeline` 結束 | 涵蓋上兩段 |

### 2.2 重要語意：2∥3 並行，總耗時非相加

Phase 2、3 由 `BlueprintPreparer` fork-join 並行（`blueprint_preparer.py:32`），所以

```
t_phase234  =  t_prep + t_phase4  ≈  max(t2, t3) + t4    （真實經過時間）
            ≠  t2 + t3 + t4                               （這是各自相加，會比實際久）
```

文件採「真實經過時間」，這才是使用者實際等待的秒數。`t_prep` 一併輸出，作為「Phase 2+3 並行段」的觀測值。

### 2.3 邊界情況

- **微調模式（refinement）**：Phase 2/3 直接讀本地快取、跳過 `prepare()`（`director_service.py:379-392`），此時 `t_prep ≈ 0`，`t_phase234 ≈ t_phase4`，屬正確行為，文件不另做特例。
- 計時用 `time.perf_counter()`（單調時鐘，不受系統時間調整影響）。

### 2.4 輸出去向

兩條並行：
1. **print**：沿用既有 `[Service] ⏱ ...` 慣例（與 `director_service.py:414` 一致）。
2. **job result dict**：把 `timings` 併入 `run_workflow` 回傳（`director_service.py:453-457`）。此 dict 經 `async_job_runner` 走 WS `JOB_FINISHED` 與 `GET /api/jobs/{job_id}`，前端即可取得。

```jsonc
// run_workflow 回傳新增欄位（示意）
{
  "blueprint": { ... },
  "timings": { "phase4_sec": 8.3, "phase234_sec": 21.7, "prep_sec": 13.4 }
}
```

---

## 3. 需求二：分 Phase 真實金額統計

### 3.1 計量資料來源（只能 token 倒推）

Gemini 回應只有 `response.usage_metadata`（純 token 數），**無任何金額欄位**。可用欄位：

| 欄位 | 意義 |
|---|---|
| `prompt_token_count` | 輸入總 token（含影片/圖片/音訊換算） |
| `candidates_token_count` | 輸出 token |
| `thoughts_token_count` | 思考 token（思考模型；計費算 output） |
| `cached_content_token_count` | 命中快取的輸入 token（折扣價） |
| `prompt_tokens_details` | **逐模態**輸入明細：`[{modality, token_count}, ...]`（精度關鍵） |

成本 = token × 官方單價。是「依公開價目表推估」，非帳單實收（free tier、抵用金、帳戶折扣只能去 Cloud Billing 對，API 拿不到）。

### 3.2 定價表 `config/pricing_config.py`（新增）

以 dataclass 定義「每模型 × 每模態」的單價（具名常數、禁 magic number）。結構支援模態分價與快取折扣；確切數值於實作時填自官方價目表。

```python
# 示意結構（非最終程式）
@dataclass(frozen=True)
class ModelPricing:
    """單一模型的 token 單價（USD / 1M tokens）。"""
    input_text: float          # 文字/圖片/影片輸入（多數 Gemini 同價）
    input_audio: float | None  # 音訊輸入（部分模型另計，如 2.5 Flash）
    output: float              # 輸出（思考 token 併入此價）
    cached_input: float | None # 快取命中輸入（折扣）

# TaskMode 用的模型 → 單價（值待官方價目表確認，見 §6 檢核表）
MODEL_PRICING: dict[str, ModelPricing] = {
    "gemini-2.5-flash-lite":        ModelPricing(...),  # 1b / 3   ← 單價待確認
    "gemini-3.1-flash-lite-preview": ModelPricing(...), # 1c / 2   ← 含音訊
    "gemini-3.5-flash":             ModelPricing(...),  # 4
}
TOKENS_PER_MILLION = 1_000_000  # 單價以每 1M token 計，換算用具名常數
```

> 已查到的單價（實作時務必再核對官方頁，含 preview id）：
> - `gemini-2.5-flash-lite`：**待確認**（約 $0.10 / $0.40，需核）
> - `gemini-3.1-flash-lite-preview`：$0.25 in / $1.50 out（音訊輸入是否另計需核）
> - `gemini-3.5-flash`：$1.50 in / $9.00 out / $0.15 cached

### 3.3 帳本 `UsageLedger`（新增，建議置於 `model/infra/usage_ledger.py`）

放在 `model/infra/` 是為了讓 `GeminiModelManager`（在 `model/managers/`）能 import 而不造成 `model → backend` 反向依賴。

```python
class Phase(Enum):
    """成本歸屬的階段標籤。"""
    PHASE1 = "phase1"; PHASE2 = "phase2"; PHASE3 = "phase3"; PHASE4 = "phase4"

@dataclass(frozen=True)
class UsageRecord:
    """單次 Gemini 呼叫的用量與推估成本。"""
    phase: Phase
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

class UsageLedger:
    """執行緒安全的成本累加器（per-job 一份）。

    Phase 1 的 pipeline 多緒並發，故累加以 threading.Lock 保護。
    summary() 回傳逐 Phase 的 {tokens, cost_usd} 與總計。
    """
```

- 帳本記錄保留 `model`，所以 Phase 1 內部的 **1b vs 1c 子拆分可免費導出**（依 model 分組），滿足日後更細的需求。

### 3.4 Phase 歸屬：`contextvars` + `phase_scope`

用兩個 module 級 `contextvars`：`_active_ledger`（per-job 帳本）、`_current_phase`。提供 context manager：

| context manager | 設在哪 | 標記 |
|---|---|---|
| `cost_session(ledger)` | `run_phase1` 全段、`run_workflow` 全段 | 綁定該 job 的帳本 |
| `phase_scope(Phase.X)` | 見下 | 當前 Phase |

`phase_scope` 設置點：

| Phase | 設置位置 |
|---|---|
| 1 | `run_phase1` 函式體（`director_service.py:158`，整段 = PHASE1） |
| 2 | `TemplateDnaProducer.produce`（`template_dna_producer.py:39`，於各自 producer 緒頂端） |
| 3 | `MusicDnaProducer.produce`（producer 緒頂端） |
| 4 | `DirectorFacade.generate_timeline`（`director_facade.py:13`） |

記錄時讀 `_current_phase` 與 `_active_ledger`；**未綁定帳本時為 no-op（Null Object）**，CLI 直跑或無 job 情境安全略過。

### 3.5 ⚠️ 跨執行緒傳播（本需求唯一動到共用 infra 的地方）

`contextvars` 不會自動跨 `ThreadPoolExecutor`。而 **Phase 1 與 Phase 2 的 Gemini 呼叫都發生在 pipeline 的 worker 緒裡**（不是設 `phase_scope` 的那條緒），若不處理會記錯 Phase。

解法是標準慣例：在 submit 當下用 `contextvars.copy_context()` 捕捉父緒 context，讓任務在副本內跑（每次 submit 各自複製 → 重用緒之間不互相污染）。需包覆的兩個 submit 點：

| 位置 | 角色 |
|---|---|
| `resource_executor.py:41` `self._pool.submit(...)` | pipeline 各資源池（含 API/Gemini stage）的葉節點 submit |
| `hybrid_scheduler.py:67` `driver_pool.submit(...)` | pipeline 的 driver 緒 |

包覆後，`run_phase1`（PHASE1）與 `TemplateDnaProducer.produce`（PHASE2）所設的 phase，會正確流入其下所有 pipeline 緒。Phase 3、4 無巢狀 pool，`phase_scope` 直接生效、無需包覆。

> 風險評估：`copy_context().run(fn)` 只是在 context 副本內執行 fn，不改變執行緒模型、Future、例外傳遞，blast radius 小；但它確實是**共用 pipeline infra**，列為實作時最需回歸測試的一處。

### 3.6 單一記錄點（收斂 4 個出口）

在 `GeminiModelManager` 加一個私有 helper：

```python
def _record_usage(self, response, model: str) -> None:
    """讀 response.usage_metadata，依 _current_phase 記入 _active_ledger（無帳本則 no-op）。"""
```

- 出口 A/B/C（§1.2）：取得 `response` 後各呼叫一次 `_record_usage`。
- 出口 D（music）：把 `_extract_search_query` 改成走 manager 的新方法（如 `generate_text(mode, ...)`），由該方法內部統一 `_record_usage`，順手修掉「繞過 manager」的封裝破口。

→ 全系統「讀 usage_metadata 並計價」只有這一處。

### 3.7 精度分級（目標：Level 1）

| Level | 做法 | 用到的欄位 | 對應 Phase |
|---|---|---|---|
| 0 | 每模型一個輸入價 × 總 token | `prompt_token_count` | 粗估 |
| **1（目標）** | 輸入**分模態**計價（文字/影片/音訊各自單價） | `prompt_tokens_details` | **1c / 2（影片+音訊為主）** |
| 2（預留） | 快取折扣 + 思考 token 併輸出 | `cached_content_token_count`、`thoughts_token_count` | 4（有 cached $0.15） |

- 新模型陣容無 Pro，故 **>200k 階梯價（Level 3）暫不需要**（3.5 Flash 為單一價，實作時核對）。
- 輸出成本一律 = `(candidates_token_count + thoughts_token_count) × output 價`。
- 計價函式 walk `prompt_tokens_details` 逐模態加總；缺明細時退回 Level 0（用總數 × `input_text`）。

### 3.8 輸出去向（per-job）

成本按 job 邊界分兩處落地：

| Job | 涵蓋 Phase | 落地點 |
|---|---|---|
| Phase 1 job（`run_phase1`） | PHASE1（含 1b/1c） | 結束 print + 併入該 job 回傳 |
| 生成 job（`run_workflow`） | PHASE2 / 3 / 4 | 結束 print + 併入回傳 `costs` |

```jsonc
// run_workflow 回傳新增（與 timings 並列）
{
  "costs": {
    "phase2": { "model": "gemini-3.1-flash-lite-preview", "input_tokens": 41000, "output_tokens": 1200, "cost_usd": 0.0123 },
    "phase3": { "model": "gemini-2.5-flash-lite",        "input_tokens": 320,   "output_tokens": 40,   "cost_usd": 0.00005 },
    "phase4": { "model": "gemini-3.5-flash",             "input_tokens": 18000, "output_tokens": 3500, "cost_usd": 0.0585 },
    "total_usd": 0.0709
  }
}
```

> 「分開統計 Phase 1/2/3/4」橫跨兩個 job：Phase 1 在素材頁的分析 job、Phase 2/3/4 在生成 job。兩者帳本各自獨立（per-job），各自輸出。

---

## 4. 需求三：分任務選模型

### 4.1 目標模型對照表

| 任務 | TaskMode | 現況 | **目標模型** | 理由 |
|---|---|---|---|---|
| 1a SIMPLE | `BASIC_MEDIA_ANALYSIS` | 本地 Qwen | 本地 Qwen（不動，$0） | — |
| 1b 深度圖片 | `DEEP_IMAGE_ANALYSIS` | 2.5 Flash | **2.5 Flash-Lite** | 圖片較易；需確認仍贏過 Qwen |
| 1c COMPLEX 影片 | `VIDEO_EVENT_INDEX` | 2.5 Flash | **3.1 Flash-Lite** | 比 2.5 Flash 更便宜+更快+ASR 更佳（最大成本中心） |
| 2 範本分析 | `TEMPLATE_ANALYSIS` | 2.5 Flash | **3.1 Flash-Lite** | 同 1c |
| 3 配樂關鍵字 | `MUSIC_SEARCH_QUERY` | 2.5 Flash | **2.5 Flash-Lite** | 任務極簡，取最便宜 |
| 4 導演藍圖 | `DIRECTOR_BLUEPRINT` | 3.1 Pro | **3.5 Flash** | 結構化+agentic 勝出、便宜且延遲遠低於 Pro（25.6s TTFT） |

### 4.2 架構改動：兩槽 → per-TaskMode 設定（Configuration Object）

`config/model_config.py` 新增以 TaskMode value 為鍵的對照（沿用該檔的 Configuration Object 風格）：

```python
# 示意；TaskMode.value 為鍵，值為 Gemini model id
GEMINI_TASK_MODEL: dict[str, str] = {
    TaskMode.DEEP_IMAGE_ANALYSIS.value: "gemini-2.5-flash-lite",
    TaskMode.VIDEO_EVENT_INDEX.value:   "gemini-3.1-flash-lite-preview",
    TaskMode.TEMPLATE_ANALYSIS.value:   "gemini-3.1-flash-lite-preview",
    TaskMode.MUSIC_SEARCH_QUERY.value:  "gemini-2.5-flash-lite",
    TaskMode.DIRECTOR_BLUEPRINT.value:  "gemini-3.5-flash",
}
# 找不到對應時的後備模型（避免 KeyError）
GEMINI_FALLBACK_MODEL = "gemini-2.5-flash"
```

- 舊的 `GEMINI_DEFAULT_MODEL` / `GEMINI_STRONG_MODEL` 可保留為相容後備，或在改完所有呼叫點後移除（見 §6）。
- 每個 model id 旁的 env 覆寫（如 `os.getenv`）可留作 A/B 切換的開關，方便不改碼換模型。

### 4.3 各呼叫點改動

| 呼叫點 | 現況取模型 | 改為 |
|---|---|---|
| `analyze_media`（1b/1c/2） | `self.default_model` | 依傳入的 `mode` 查 `GEMINI_TASK_MODEL[mode.value]` |
| music `_extract_search_query`（3） | `gemini.default_model` | 走 §3.6 的新 manager 方法，內部依 `MUSIC_SEARCH_QUERY` 查表 |
| `generate_director_plan`（4） | `self.strong_model` | 查 `GEMINI_TASK_MODEL[DIRECTOR_BLUEPRINT.value]` |

`analyze_media` 已帶 `mode: TaskMode`（`gemini_model_manager.py:83`），所以模型解析只是「`mode` → 查表」一步，`_generate_inline` / `_analyze_via_file_api` 改用解析出的 model 即可。

### 4.4 與成本/定價的連動

- §3.2 的 `MODEL_PRICING` 必須涵蓋這三顆新模型（2.5 Flash-Lite、3.1 Flash-Lite、3.5 Flash）。
- 模型一換，§3.8 的 `costs` 會自動反映新單價——這也是驗證「換模型省了多少」的數據來源。

---

## 5. 要新增 / 修改的檔案

**新增**
- `config/pricing_config.py` — `ModelPricing` dataclass + `MODEL_PRICING` 表。
- `model/infra/usage_ledger.py` — `Phase`、`UsageRecord`、`UsageLedger`、`contextvars`、`phase_scope`、`cost_session`、計價函式。

**修改**
- `config/model_config.py` — 新增 `GEMINI_TASK_MODEL` / `GEMINI_FALLBACK_MODEL`。
- `model/managers/gemini_model_manager.py` — `_record_usage`、依 mode 查表選模型、新增 text 生成方法供 music 用。
- `director_agent/music_director.py` — `_extract_search_query` 改走 manager 方法。
- `backend/services/director_service.py` — `run_phase1` / `run_workflow` 包 `cost_session`；`run_workflow` 加三段計時與 `timings`/`costs` 回傳。
- `director_agent/blueprint/template_dna_producer.py`、`music_dna_producer.py` — 各自 `produce` 包 `phase_scope`。
- `director_agent/director_facade.py` — `generate_timeline` 包 `phase_scope(PHASE4)`。
- `media_processor/pipeline/executor/resource_executor.py`、`media_processor/pipeline/scheduler/hybrid_scheduler.py` — submit 包 `copy_context`（§3.5）。

---

## 6. 實作順序建議（分階段，降風險）

1. **選模型（§4）**：純設定，立即見效、可獨立驗證。先拆 `GEMINI_TASK_MODEL`、改三個呼叫點。
2. **計時（§2）**：`run_workflow` 內局部改動，無跨緒問題，風險最低。
3. **成本骨架（§3.2–3.4, 3.6）**：定價表 + 帳本 + 單一記錄點 + `phase_scope`，先在**無巢狀緒**的 Phase 3/4 驗證數字正確。
4. **跨緒傳播（§3.5）**：最後上 `copy_context`，讓 Phase 1/2 的金額也正確；對 pipeline 做回歸。
5. **精度升級（§3.7 Level 1）**：把計價從總數改成 walk `prompt_tokens_details`。

---

## 7. 待確認事項（實作前檢核）

- [ ] **確認三顆模型的 production model id 與 GA/SLA 狀態**：`gemini-3.1-flash-lite-preview` 仍掛 `-preview`（多數來源稱 Preview、一處稱 5 月 GA）；`gemini-3.5-flash`、`gemini-2.5-flash-lite` 的正式 id。
- [ ] **核對官方單價**：尤其 `gemini-2.5-flash-lite` 的 in/out、以及各模型**音訊輸入是否與文字/影片不同價**（決定 Level 1 是否真的有差）。
- [ ] **log 一筆真實 `usage_metadata`** 確認 `prompt_tokens_details`、`cached_content_token_count`、`thoughts_token_count` 在當前 google-genai 版本實際吐出的形狀與欄位名。
- [ ] **1b 驗證**：2.5 Flash-Lite 的深度圖片輸出需仍**優於本地 Qwen SIMPLE**，否則該路徑失去付費意義（應改路由回 SIMPLE）。
- [ ] **1c / 4 A/B（換模型品質把關，可與本次實作並行）**：1c 量 bbox/時間戳/轉錄、注意 3.1 Flash-Lite 的 factuality 較低（描述幻覺）；4 用 critic 首次通過率+重試次數 gate，並人眼看成品品味。

---

## 8. 不在本次範圍（Out of Scope）

- 不接 Google Cloud Billing（無法分 Phase/即時；本設計只做價目表推估）。
- 不換 Phase 1/2 的廠商（仍 Gemini；只在 Gemini 家族內換型號）。
- 不做成本的持久化/歷史儀表板（先只走 print + job result dict；日後要存再議）。
- 不寫 test file（依專案規範）。
