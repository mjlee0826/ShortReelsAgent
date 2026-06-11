# Blueprint 準備階段:Template ∥ Music 並行化設計

> 本文件說明 blueprint 生成(Phase 2 Template DNA + Phase 3 Music DNA)的架構重整:
> 把 template_engine 的素材深度感知收斂到既有 pipeline、把 music_director 的 GPU 工作
> 接到共享資源層,並以 fork-join 讓兩條獨立分支並行,縮短 blueprint 生成時間。
> 與 `lock_design.md`(GPU 三層鎖)、pipeline 的 `runner.py` / `model_pool_registry.py` 配套。

---

## 1. 背景:現況的三個問題

EditorPage 生成 blueprint 時,若使用者填了 template URL,後端走 `TemplateAnalyzerFacade`。
盤點 `director_service.run_workflow` 的執行鏈後,發現三個結構問題:

| # | 問題 | 位置 |
|---|---|---|
| P1 | template 走**舊版** `ComplexVideoProcessor`(legacy 單發 `process()`),而 Phase 1 素材早已改走新 pipeline DAG | `director_service.py:57` 持有 `template_analyzer`,但 `:56` 已持有 `pipeline_runner` |
| P2 | 重複勞動:scene cut 與抽音軌各跑兩次(facade 一次、Complex 內部一次) | `template_analyzer_facade.py:38-47` |
| P3 | 完全序列:template(在 service)→ music(卡在狀態機 `IntentState`)→ scheduling,兩段獨立工作沒有重疊 | `run_workflow` + `intent_state.py` |

關鍵事實:`legacy_video_stage.py` docstring 已寫明 `VideoProcessor / ComplexVideoProcessor`
是「保留作 fallback」的舊版;**template_engine 是全系統唯一還直接吃舊路徑的地方**。

---

## 2. 核心原則:Tier A 共用,Tier B 因地制宜

把 pipeline 這個「架構」拆成兩個其實不同的層,是整份設計的判準。

### Tier A — 資源層(全系統共用)

| 共享物件 | 服務對象 | 解決什麼 |
|---|---|---|
| `ModelPoolRegistry`(+ GpuGate / BudgetGate) | 所有 **GPU 模型**推論 | 全域 VRAM 預算、同卡 forward 互斥 → **並行不撞車** |
| `ExecutorRegistry`(IO/CPU/GPU/API 四池) | IO / API / CPU 工作 | 全域重疊、API RPS 上限 |

`ModelPoolRegistry` 是 **process 級單例**(`instance()`),由 `PipelineRunner` 建構時註冊。
任何模組要跑 GPU,都該透過它 borrow,而非自建 `XxxModelManager()` singleton。

### Tier B — 編排層(因地制宜)

| 場景 | item 特性 | 該用的編排 |
|---|---|---|
| Phase 1 素材感知 | **大量同質** asset × 多 GPU stage | full DAG-Stage pipeline(`HybridScheduler` + `Pipeline` + `StageNode`)— **既有** |
| Blueprint 準備 | **少數異質**獨立分支(template ∥ music) | 輕量 **fork-join**(本文件)— 新增 |
| director_service | 序列 phase + 持久化 | 維持**協調者**,不 DAG 化 |

> 判準一句話:**item 多且同質 → full pipeline;少數異質獨立任務 → fork-join。**
> Phase 1 已在素材頁做完並快取(見 `run_workflow` 註解),blueprint 時剩下的 DAG 小到
> 只有 `template ∥ music → schedule → reflect`,硬套 `AssetContext` 是 over-engineering。

---

## 3. 相依圖

```
                         director_service.run_workflow
                                    │
                  ┌─────────────────┴──────────────────┐
                  │  BlueprintPreparer.prepare(ctx)     │  ← fork-join (driver=2)
                  └──────┬───────────────────────┬──────┘
            fork ────────┤                       ├──────── fork
                         ▼                       ▼
              TemplateDnaProducer        MusicDnaProducer
                  │                          │
       runner.run([template])        MusicDirector.resolve()
       (pipeline DAG，內部 borrow)         │
       + beats(librosa CPU)          MusicEngineFacade
       + BlueprintBuilder            └ Whisper → borrow_for_batch (GPU pool)
                  │                    └ VAD     → run_vad          (CPU pool)
                  └───────────┬───────────┘
                         join  ▼
                  {template_dna, audio_dna}
                              │
              director.generate_timeline(兩者直接傳入)
                  SchedulingState → ReflectionState
                              │
        ┌─────────────── Tier A 全程共用 ───────────────┐
        │ ModelPoolRegistry (GpuGate / VRAM 預算) + 4 資源池 │
        └────────────────────────────────────────────────┘
```

`template_dna ⊥ audio_dna`(彼此無資料相依),`SchedulingState` 是唯一 join 點
(`scheduling_state.py:21-24` 同時吃兩者)。兩分支皆 I/O 密集(下載 / 雲端),
thread 即可重疊;GPU 段各自 borrow 同一 GpuGate,故並行不會 VRAM 翻倍。

---

## 4. 元件設計(骨架)

新增套件 `director_agent/blueprint/`。三個角色:`PrepContext`(輸入值物件)、
`DnaProducer`(分支策略抽象)、`BlueprintPreparer`(fork-join 協調器)。

> 本節骨架為**單純版**(`produce` / `prepare` 只收 `ctx`);接前端進度的 **tracker 貫穿完整版見 §10**
> ——差別僅在多透傳一個 `tracker` 參數,不影響此處的角色切分。

### 4.1 PrepContext —— 唯讀輸入(Value Object / Parameter Object)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PrepContext:
    """藍圖準備階段的唯讀輸入。

    兩分支共用同一份輸入、各取所需:template 分支用 template_url;
    music 分支用 music_strategy / user_music_file / user_prompt / regenerate_music。
    frozen 確保並行讀取期間不被任一分支竄改。
    """
    template_url: str | None
    music_strategy: str
    user_music_file: str | None      # 已解析為絕對路徑
    user_prompt: str
    regenerate_music: bool
```

### 4.2 DnaProducer —— 分支抽象(Strategy Pattern)

```python
from abc import ABC, abstractmethod

class DnaProducer(ABC):
    """藍圖準備的「DNA 生產者」抽象。

    每個生產者吃同一份 PrepContext,獨立產出藍圖所需的一塊 DNA;
    彼此無資料相依,故可由 BlueprintPreparer 以 fork-join 並行。
    """

    name: str  # 子類別提供;供日誌、進度、結果鍵

    @abstractmethod
    def produce(self, ctx: PrepContext) -> dict:
        """產出本分支的 DNA;不適用 / 取不到時回空 dict(呼叫端視為缺該段)。"""
```

### 4.3 TemplateDnaProducer —— 委派 pipeline,不自造 DAG

```python
import os
from media_tools.media_downloader import MediaDownloader
from media_tools.ffmpeg_adapter import FFmpegAdapter
from media_tools.audio_beat_extractor import AudioBeatExtractor
from template_engine.blueprint_builder import BlueprintBuilder
from media_processor.video_strategy import VideoStrategy

class TemplateDnaProducer(DnaProducer):
    """Template 分支:素材深度感知委派共享 PipelineRunner(走既有 complex 影片 DAG),
    再補物理節奏(beats)與 DNA 組裝(Builder)。

    重點:不自己造 DAG —— complex 影片分析的 DAG 已存在於 pipeline,本生產者只是它的
    consumer + 後處理。scene_cuts 直接取 pipeline metadata,不再重跑 SceneCutExtractor(解 P2)。
    """

    name = "template_dna"

    def __init__(self, runner):
        # 注入 director_service 已建好、模型已 warm 的共享 runner(跨請求重用,不可 new)
        self._runner = runner
        self._downloader = MediaDownloader()
        self._ffmpeg = FFmpegAdapter()
        self._beat_extractor = AudioBeatExtractor()

    def produce(self, ctx: PrepContext) -> dict:
        if not ctx.template_url:
            return {}

        # 1. 下載 template 影片
        media_info = self._downloader.fetch_video(ctx.template_url)
        video = media_info["video_path"]
        base_dir = os.path.dirname(video)
        asset_id = os.path.basename(video)

        # 2. 深度感知:走共享 pipeline(stage 並行、內部自動 borrow 模型);強制 COMPLEX 策略
        results = self._runner.run(
            [video],
            base_dir=base_dir,
            asset_strategies={asset_id: VideoStrategy.COMPLEX.value},
        )
        if not results:
            raise RuntimeError("Template 深度分析失敗(pipeline 無 success 結果)")
        complex_meta = results[0]["metadata"]

        # 3. 物理節奏:beats 是 template 專屬、librosa 純 CPU,留在本分支(不入 pipeline)
        a_only = os.path.join(base_dir, f"{os.path.splitext(asset_id)[0]}_a_only.wav")
        self._ffmpeg.extract_ai_audio(video, a_only)
        beats = self._beat_extractor.get_beats(a_only)

        # 4. 組裝 DNA;scene_cuts 取自 pipeline metadata(解 P2,不再自跑場景偵測)
        return (
            BlueprintBuilder()
            .set_info(media_info["music_metadata"], media_info["original_url"])
            .set_local_assets(original_video=video, video_only="", audio_only=a_only)
            .set_physical_cuts(complex_meta.get("scene_cuts", []))
            .set_audio_features(beats)
            .ingest_complex_metadata(complex_meta)
            .build()
        )
```

### 4.4 MusicDnaProducer —— 委派 MusicDirector

```python
from director_agent.music_director import MusicDirector

class MusicDnaProducer(DnaProducer):
    """Music 分支:委派 MusicDirector 解析配樂 DNA。

    MusicDirector→MusicEngineFacade 的 Whisper/VAD 已改 borrow 共享 ModelPoolRegistry,
    與 template 分支的 GPU 工作共用同一 GpuGate,並行不搶 VRAM(見 §5)。
    """

    name = "music_dna"

    def __init__(self):
        self._director = MusicDirector()

    def produce(self, ctx: PrepContext) -> dict:
        # 純對話微調:不重抓配樂,沿用上一版 bgm(對齊原 IntentState 行為)
        if not ctx.regenerate_music:
            return {}
        return self._director.resolve(
            music_strategy=ctx.music_strategy,
            user_music_file=ctx.user_music_file,
            user_prompt=ctx.user_prompt,
        )
```

### 4.5 BlueprintPreparer —— fork-join 協調器(縮小版 HybridScheduler)

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

# driver thread 命名前綴,方便除錯辨識(對齊 HybridScheduler 慣例)
_PREP_THREAD_PREFIX = "blueprint-prep"

class BlueprintPreparer:
    """藍圖準備階段的 fork-join 協調器。

    結構上即「少數 driver thread + 共享 Tier A 資源」的縮小版 HybridScheduler:
    把彼此獨立的 DnaProducer 並行跑,join 後回傳 {name: dna}。GPU 工作各自 borrow
    ModelPoolRegistry → 共用 GpuGate,故並行不會 VRAM 翻倍;不需要 asset-DAG 機械。
    """

    def __init__(self, producers: list[DnaProducer]):
        self._producers = producers

    def prepare(self, ctx: PrepContext) -> dict[str, dict]:
        """並行跑完所有分支,回傳以 producer.name 為鍵的 DNA 字典。"""
        # driver 數 = 分支數;皆 I/O 密集(下載 / 雲端),thread 足以重疊(GIL 在 I/O 釋放)
        with ThreadPoolExecutor(
            max_workers=len(self._producers),
            thread_name_prefix=_PREP_THREAD_PREFIX,
        ) as pool:
            futures = {pool.submit(self._safe_produce, p, ctx): p for p in self._producers}
            return {futures[f].name: f.result() for f in as_completed(futures)}

    @staticmethod
    def _safe_produce(producer: DnaProducer, ctx: PrepContext) -> dict:
        """單一分支例外不拖垮另一分支:吞例外回空 dict(對齊既有『取不到配樂視為無配樂』)。"""
        try:
            return producer.produce(ctx)
        except Exception as exc:  # noqa: BLE001 - 刻意隔離分支例外
            print(f"[BlueprintPreparer] 分支 {producer.name} 失敗: {exc}")
            return {}
```

---

## 5. music_director 接 Tier A 的改動

改動點在 `MusicEngineFacade._fetch_lyrics`(`music_engine_facade.py:188-212`):把自建的
`whisper_engine` / `vad_engine` lazy property 換成 borrow 共享 pool。

```python
from media_processor.pipeline.executor.model_pool_registry import borrow_for_batch, run_vad
from model.managers.whisper_model_manager import WhisperModelManager

# borrow 時的 stage 名稱常數(供 borrow 等待事件標示,禁 magic string)
_MUSIC_LYRICS_STAGE = "music_lyrics"

def _fetch_lyrics(self, query: str, fallback_audio_path: str) -> dict:
    # 路 1:LRClib 歌詞 DB(無 GPU 成本)—— 不變
    lyrics_from_db = self.lyrics_adapter.fetch_synced_lyrics(query)
    if lyrics_from_db:
        return lyrics_from_db

    # 路 2:VAD 改 borrow 共享 CPU pool(與 pipeline VAD 同池,不再各開 singleton)
    if not run_vad(lambda v: v.has_speech(fallback_audio_path)):
        return {"chunks": [], "text": "", "source": "vad_silent"}

    # Whisper 改 borrow 共享 GPU pool(與 template 分支共用 GpuGate / VRAM 預算)
    whisper_result = borrow_for_batch(
        WhisperModelManager,
        _MUSIC_LYRICS_STAGE,
        lambda m: m.transcribe(fallback_audio_path),
    )
    return {
        "chunks": whisper_result.get("chunks", []),
        "text": whisper_result.get("text", ""),
        "source": "whisper",
    }
```

連帶移除 `MusicEngineFacade` 的 `_whisper` / `_vad` 欄位與 `whisper_engine` / `vad_engine`
property(改 borrow 後變死碼)。

> **共用深度是可選的**:最小做法只改 GPU(本節,根治 VRAM 撞車);IO(下載)/ API(Gemini)
> 是否也丟 `ExecutorRegistry` 共用池,對 2 分支規模而言屬非必要優化,可後續再做。

---

## 6. Tier A 生命週期:warmup 解耦到 lifespan

> 與「重用共享 runner、不 new」(§3 / §4.3)同屬 Tier A 的生命週期管理。
> 本節獨立於 fork-join,可單獨落地。

### 6.1 現況問題

warmup 目前綁在 **import 期**觸發,鏈路:

```
backend/main.py:19          import director router
  → director_service.py:507  director_service = DirectorService()  ← 模組級單例，import 即執行
    → DirectorService.__init__:56  PipelineRunner()
      → runner.py:76-80      if EAGER_MODELS: model_pool_registry.warm_up()
```

即「import 這個模組」本身就有「載入數 GB 權重上 GPU」的重量級副作用。衍生四個問題:

| # | 問題 | 後果 |
|---|---|---|
| W1 | import 副作用 | 任何 import 到 director_service 的路徑(測試 / CLI / 腳本 / IDE 內省)都連鎖全載權重 |
| W2 | CUDA + fork 不相容 | `gunicorn --preload` / 多 worker 時 import 在 fork **之前**建 CUDA context → fork 出的 worker context 壞掉 |
| W3 | 失敗無法優雅處理 | warmup 在 import 期丟例外 → 整個模組 import 失敗、堆疊難讀,無法降級 lazy |
| W4 | warmup 進度推不出去 | warmup 早於 lifespan 的 `progress_hub.ensure_loop()`,`MODEL_WARMUP` 事件只進 replay buffer、無法即時廣播 |

> 注意:lifespan(`main.py:28-41`)目前只處理 `ensure_loop()` 與 ingestion poller,**沒碰模型 warmup**。

### 6.2 改法:建構與 warmup 解耦

核心:`__init__` 只建 registry / pool 殼(便宜),warmup 改由 lifespan 顯式呼叫
(每 worker 各跑一次、在 fork **之後**)。

```python
# PipelineRunner.__init__:移除 if EAGER_MODELS: warm_up()，改新增公開方法
def warm_up(self) -> None:
    """顯式預載熱門模型(供 lifespan 在 fork 後呼叫);無 CUDA 時 no-op。"""
    self._model_pool_registry.warm_up()

# DirectorService(eager_models=False) 透傳；模組級單例 import 不再有重副作用
director_service = DirectorService(eager_models=False)

# backend/main.py lifespan：排在 ensure_loop 之後，warmup 事件才能即時廣播(解 W4)
@asynccontextmanager
async def lifespan(app: FastAPI):
    progress_hub.ensure_loop()
    # 丟 thread 不阻塞 event loop(startup 期間 readiness 探針仍可回應)
    await asyncio.to_thread(director_service.pipeline_runner.warm_up)
    if ENABLE_INGESTION_POLLER:
        await ingestion_poller.start()
    try:
        yield
    finally:
        ...
```

要動三處:`PipelineRunner.__init__` 移除 import 期 warmup + 加公開 `warm_up()`、
`DirectorService` 透傳 `eager_models`、`lifespan` 呼叫。`EAGER_MODELS` 旗標語意保留,改由 lifespan 讀。

### 6.3 注意

- **CLI / 非 server 入口**:改後變「第一次 borrow 時 lazy 載入」(`ModelPoolRegistry.instance()` 本就支援);
  需確認無程式碼假設「import 完模型即 ready」。
- **`to_thread`**:不包也行(startup 尚未收請求),包了好處是 lifespan 其他步驟可交錯、loop 可回應 health check。
- **適用條件**:單 worker、不 fork、不從測試 / CLI import 的場景,現況「能動」;此為 robustness / hygiene 改善
  (且順手解 W1 / W4)。改動小(三處)故仍建議做。

### 6.4 通用慣例:便宜建構 + 兩階段啟動

warmup 解耦不是特例,而是一條**全 backend 適用的初始化慣例**:目標不是「所有初始化都進 lifespan」,
而是「**import 期不做重事 / 有副作用的事**」。判準看的是「建構時碰到什麼」,而非「是不是初始化」:

| 碰到這些 → 放 lifespan(兩階段) | 純粹這樣 → 留 module level(便宜建構) |
|---|---|
| GPU / CUDA context | 只設 `self.xxx = ...` 純狀態 |
| 網路請求(fetch JWKS、連 API) | 持有 lazy lock / 空 cache |
| 開背景 thread / asyncio task | 注入其他便宜物件 |
| 捕捉 event loop | 讀 config 常數 |
| 開 DB pool / 掃磁碟 | |
| 有**順序相依**(A 要先於 B) | |

> CUDA / 網路 / thread / loop 還有硬理由:多 worker / fork 時必須在 **fork 之後、每 worker 各做一次**,
> 留在 import 期會在 fork 前就建好 → 壞掉(同 W2)。

**範式**:`__init__` 便宜(純建構)+ 顯式 `start()` / `warm_up()` / `activate()` 由 lifespan 呼叫。
**保留** module 級單例**物件**(api 層靠 `from services.x import singleton` 單向取用);搬進 lifespan 的是
**重的啟動步驟**,不是物件建構 —— 否則要改成 `app.state.xxx` 並重寫所有呼叫點,無好處。

現況盤點(本 codebase 多數已符合,新增 service 請對齊):

| 元件 | 現況 | 評斷 |
|---|---|---|
| `LogtoJWTVerifier` | `__init__` 只設空 cache;JWKS `httpx.get` 第一次驗 token 才打 + TTL cache | ✅ 教科書 lazy |
| `ingestion_poller` | module 級建構,`.start()` / `.stop()` 在 lifespan | ✅ 兩階段範式 |
| stores / `progress_hub` / `job_manager` / `phase1_lock` | 純狀態 / lazy lock;`ensure_loop()` 在 lifespan | ✅ |
| **`director_service`** | `__init__` → `PipelineRunner()` → **GPU warmup**(import 期) | ❌ 唯一 outlier → 本節 §6.2 修 |

> 結論:**只有 `director_service` 需要改**;其餘已符合慣例,不要動。新增 backend service 時以本表為準。

---

## 7. director_service 接線

`run_workflow` 內 §1 的「序列 template + 狀態機 music」改為一次 fork-join。

```python
# __init__:組裝協調器(注入共享 runner)
self.blueprint_preparer = BlueprintPreparer([
    TemplateDnaProducer(self.pipeline_runner),
    MusicDnaProducer(),
])

# run_workflow:取代原本的 template extract(:355-361)+ 狀態機內 music
prep_ctx = PrepContext(
    template_url=template,
    music_strategy=music_strategy,
    user_music_file=user_music_file_path,
    user_prompt=enhanced_prompt,
    regenerate_music=regenerate_music,
)
dna = self.blueprint_preparer.prepare(prep_ctx)
template_dna = dna.get("template_dna") or None
audio_dna = dna.get("music_dna") or None

# Phase 2 DNA 落地(維持原快取行為)
if template_dna:
    with open(phase2_dump_path, "w", encoding="utf-8") as f:
        json.dump(template_dna, f, ensure_ascii=False, indent=2)

# director 改為純 scheduling + reflection:audio_dna 直接傳入,IntentState 移除
final_blueprint, _ = self.director.generate_timeline(
    user_prompt=enhanced_prompt,
    raw_assets=raw_assets_metadata,
    template_dna=template_dna,
    audio_dna=audio_dna,             # 新增參數,取代狀態機內解析
    previous_timeline=old_timeline,
    previous_bgm_track=previous_bgm_track,
    regenerate_music=regenerate_music,
)
```

`DirectorFacade.generate_timeline` 對應改動:狀態機入口由 `IntentState` 改為 `SchedulingState`,
`audio_dna` 從參數注入 context;`IntentState` 退場(`change_music` 仍直接用 `MusicDirector`,不受影響)。

---

## 8. 遷移檢查清單與風險

| 項目 | 說明 | 風險 |
|---|---|---|
| **欄位對齊** | `BlueprintBuilder.ingest_complex_metadata` 需要 `cinematic_critique` / `audio_transcript` / `multimodal_event_index`;須確認 pipeline complex 路徑的 `AssemblyVideoStage` metadata 鍵與舊 `ComplexVideoProcessor` 一致 | 中 — 鍵不一致會讓 DNA 缺欄,需逐欄比對 |
| **local_assets.video_only** | 新流程不再產 `v_only`;須確認下游(render?)是否真的需要,否則此欄留空 | 低 — 確認後決定是否補產 |
| **a_only 重複抽取** | beats 仍自抽一次音軌,與 pipeline 內部 `AudioExtractionStage`(temp、已清)重疊 | 低 — 一次便宜 ffmpeg,可接受;若要省需 pipeline 導出音軌 |
| **單 asset 額外負擔** | runner 為多 asset 設計,單支 template 會帶 tracker/watchdog 負擔 | 低 — 相對 Gemini 影片分析可忽略;嫌重可改 `builder.build + pipeline.execute` |
| **IntentState 移除** | 確認除狀態機外無其他呼叫者;`change_music` 已直接用 MusicDirector | 低 |
| **warmup 解耦(§6)** | 改 lifespan 後,確認無 CLI / 腳本假設「import 完模型即 ready」;CLI 改吃 lazy borrow | 低 |
| **量測** | fork-join 只省「較短分支」;上線前後加各階段計時,確認 music 分支夠長到值得重疊,否則優先收割 P2 去重 | — |

---

## 9. 落地順序(建議)

1. **P2 去重 + Q1 走 pipeline**:`TemplateDnaProducer` 取代 `TemplateAnalyzerFacade`,template 改走共享 runner、scene_cuts 取 metadata。(先做欄位對齊驗證)
2. **music 接 Tier A**:`_fetch_lyrics` 改 borrow,移除自建 singleton。
3. **fork-join**:加 `BlueprintPreparer`,music 移出狀態機,`director_service` 接線。
4. **量測**:比對改動前後 blueprint 生成 wall time,驗證並行紅利。
5. **進度匯流上 WS(§10)**:先把 `/generate` 由同步請求改成 async job(產生 T1),再把 T1 一路注入
   `BlueprintPreparer` → 兩 producer;template 透傳給 `runner.run(tracker=)`、music 在 download / beats /
   lyrics 發 STAGE_*;前端開 WS 顯示。**依賴步驟 3**(需先有 fork-join 與兩 producer)。

> 步驟 1、2 即使不做 3 也各自有價值(去重 + 根治 VRAM 撞車),3 才是並行加速。

**warmup 解耦(§6)獨立於上述**:不依賴 1–5、可隨時單獨落地,且改動小(三處)。
建議優先做,先消掉 import 副作用(W1)與 import-期 warmup 推不出進度(W4),再進 1–5。

---

## 10. 進度可觀測性:blueprint 生成上 WS 前端

> 目標:讓 template ∥ music 兩分支的進度都即時顯示在前端。與 §5 互補 —— §5 只接 **Tier A 資源**
> (GPU 池),本節接 **進度匯流**(把兩分支事件併回使用者那條 WS)。**獨立於 §4 的 fork-join,
> 但依賴它**(要先有兩個 producer 可掛 tracker)。

### 10.0 前提發現:`/generate` 目前是同步請求,沒有 job / tracker / WS

盤點使用者實際走的生成路徑,進度基建並不存在於 blueprint 流程:

| 事實 | 位置 |
|---|---|
| `/generate` 直接 `asyncio.to_thread(run_workflow)` **同步**跑完,blueprint 走 **HTTP response body** 回傳 | `backend/api/director.py:47` |
| `run_workflow` **無 `tracker` 參數**,Phase 2–4 全程 tracker-less | `director_service.py:299` |
| WS / job 基建(`async_job_runner` → T1)**目前只服務 Phase 1**(素材頁 reanalyze、雲端 ingestion 預跑) | `assets.py:160/222`、`ingestion_provider.py:93` |

⇒ **沒有 T1、沒有 WS channel 可給 blueprint**。要前端看進度,**第一步是把 `/generate` 改成 async job**,
才會生出 T1 可往下貫穿。這是下面一切的地基。

### 10.1 三個 tracker 回顧

| | 來源 | job_id | 掛的 Observer |
|---|---|---|---|
| **T1** | `AsyncJobRunner`(背景 job) | 對外 `job_id` | `ws_progress_observer` |
| **T2** | `PipelineRunner.run()`(每次 run) | **注入則沿用 T1**;否則自建隨機 | `PrintProgressObserver` + `StallWatchdog` |
| **T3** | `ModelPoolRegistry`(啟動期) | 字面 `"startup"` | `PrintProgressObserver` |

前端 WS 經 `ProgressHub` **以 job_id 分流**,故事件要被使用者看到,必鬚同時:(a) 落在掛了
`ws_progress_observer` 的 tracker,(b) 帶**使用者的 job_id**。

> **關鍵澄清**:解法**不是**給 template / music「`subscribe(ws_progress_observer)`」。光 subscribe 而
> job_id 不對,`ProgressHub` 仍分流不到使用者那條 WS。**load-bearing 的是把帶正確 job_id 的 T1 一路
> 貫穿**;observer 已掛在 T1 上,各分支不需自行 subscribe。

### 10.2 地基:`/generate` 改 async job(產生 T1)

```python
# 1) run_workflow 增 tracker 參數(對齊 run_phase1 的簽名慣例),內部往下傳給 BlueprintPreparer
def run_workflow(self, prompt, folder_name, ..., tracker: ProgressTracker | None = None):
    ...

# 2) api/director.py:把同步 to_thread 換成 async job;前端拿 job_id 後開 WS、再取結果
@router.post("/generate")
async def generate_timeline(req: GenerateRequest, user_id: str = Depends(verify_token)):
    def work(tracker: ProgressTracker) -> dict:
        return director_service.run_workflow(..., tracker=tracker)   # T1 注入
    job_id = async_job_runner.launch(user_id, work)
    return {"job_id": job_id}
```

**定案:用 `launch`(純非同步),不用 `run_tracked_sync`。** POST 立即回 `{job_id}`;前端開
`WS /ws/progress/{job_id}` 看進度,結果改走 `GET /projects/{folder}/blueprint`(讀磁碟落地藍圖)
或 WS 的 `JOB_FINISHED` 事件。

> **為何不留 `run_tracked_sync`**:它與 `launch` **唯一差別是「原始 POST 連線要不要 held 到生成跑完」**
> —— 工作 thread、lock、磁碟落地、replay、重連需求兩者全同。`run_tracked_sync` 把結果綁在一條長連線
> (數分鐘)上,徒增 client / 反代 idle timeout(常見 60s)砍連線回 504 的風險;而**一旦要支援「退出再
> 進來接回」(§10.9),側通道 + 磁碟落地本就得建,`run_tracked_sync` 的「response body 直接帶結果」就成了
> 多餘的負債**。故定案 `launch`。

### 10.3 Template:注入 T1,自動繼承 ws / print / watchdog

`TemplateDnaProducer` 唯一改動:把 tracker 透傳給 `runner.run`。`runner.run(tracker=T1)` 會把自己的
`PrintObserver` + `StallWatchdog` 也加到 T1(既有行為),故 template stage 事件一次到齊三個 observer。

```python
def produce(self, ctx: PrepContext, tracker: ProgressTracker) -> dict:
    ...
    results = self._runner.run(
        [video],
        base_dir=base_dir,
        asset_strategies={asset_id: VideoStrategy.COMPLEX.value},
        tracker=tracker,                       # ← 注入 T1:事件帶正確 job_id 上前端
    )
```

> 這就是「proposal 1」的正確形態:**注入 T1,而非 subscribe observer**。

### 10.4 Music:給 tracker、在關鍵節點發 STAGE_*、借出改掛 T1

Music 對前端可見的核心是讓使用者看到「下載中 / 分析節拍中 / 聽寫中」,故在 `MusicEngineFacade` 三個
有感步驟發 STAGE_START/FINISH 到注入的 tracker。`MusicDirector.resolve` / facade 各加一個**可選** `tracker`
參數透傳(不傳時退化為純 print,維持 `change_music` 等舊呼叫端不變)。

```python
# music stage 名稱常數(禁 magic string;_MUSIC_LYRICS_STAGE 已於 §5 定義)
_MUSIC_STAGE_DOWNLOAD = "music_download"
_MUSIC_STAGE_BEATS    = "music_beats"
_MUSIC_ASSET_ID       = "music"            # music 無真 asset,用合成 id 供事件歸屬

def fetch_and_analyze(self, query: str, tracker: ProgressTracker | None = None) -> dict:
    ...
    with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_DOWNLOAD):   # 計時 + emit start/finish
        raw_audio_path = self.downloader.search_and_download_audio(query)
    self.ffmpeg.extract_ai_audio(raw_audio_path, standard_wav_path)
    with stage_span(tracker, _MUSIC_ASSET_ID, _MUSIC_STAGE_BEATS):
        audio_beats = self.beat_extractor.get_beats(standard_wav_path)
    lyrics_data = self._fetch_lyrics(query, standard_wav_path, tracker)   # 內部包 _MUSIC_LYRICS_STAGE
    ...
```

`stage_span` 是個小 context manager(`tracker=None` 時 no-op,免每處手寫 try/finally)。

**Whisper 借出改掛 T1(可選精修)**:§5 用 `borrow_for_batch`(→ T3 startup observer,前端看不到)。
要讓「music 等 VRAM」也上前端,給 `borrow_for_batch` 加一個可選 `tracker`,有則改用 per-run observer:

```python
def borrow_for_batch(model_class, stage_name, fn, tracker=None, asset_id=None):
    if not GPU_POOL_ENABLED:
        return fn(model_class())
    registry = ModelPoolRegistry.instance()
    observer = (
        registry.make_borrow_observer(tracker, asset_id, stage_name)   # → T1,前端可見
        if tracker is not None else registry.startup_borrow_observer(stage_name)  # → T3,沿用舊行為
    )
    return registry.get_pool(model_class).run_with_failover(fn, observer=observer)
```

VAD(`run_vad`)維持只計 `ResourceWaitClock`(無 observer 接口),其等待仍不上前端 —— 可接受
(純 CPU、不搶 VRAM,無觀測急迫性)。

### 10.5 BlueprintPreparer / director_service 接線

```python
# prepare 多收一個 tracker,透傳給每個 producer
def prepare(self, ctx: PrepContext, tracker: ProgressTracker) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=len(self._producers),
                            thread_name_prefix=_PREP_THREAD_PREFIX) as pool:
        futures = {pool.submit(self._safe_produce, p, ctx, tracker): p for p in self._producers}
        return {futures[f].name: f.result() for f in as_completed(futures)}

# run_workflow:把自己收到的 T1 直接傳入
dna = self.blueprint_preparer.prepare(prep_ctx, tracker)
```

> tracker 是**活的協作者**,刻意**不放進 `PrepContext`** —— `PrepContext` 是 frozen 唯讀輸入值物件
> (§4.1),混入 tracker 會破壞其「並行讀取期間不被竄改」的語意。故以獨立參數貫穿。

### 10.6 watchdog 與 print 的處置(澄清 proposal 2)

proposal 2 寫「music 也接 watchdog / PrintObserver / ws」,實作上要分辨三者本質不同:

| | 怎麼讓 music 取得 | 為何不是「subscribe」 |
|---|---|---|
| **ws** | §10.4 對 T1 emit STAGE_* | T1 已掛 ws_observer,emit 即到;自行 subscribe 反而 job_id 不對 |
| **PrintObserver** | **不掛** | music 本就 raw `print`,再掛會**雙重輸出** |
| **watchdog** | 對 T1 emit STAGE_* 後,**有 watchdog 訂在 T1 即自動涵蓋** | watchdog 靠訂 STAGE_* 維護「進行中清單」,不需 music 主動接 |

watchdog 生命週期注意:template 的 `runner.run` 已對 T1 起一個 watchdog,但**只活到 template run 結束**;
若 music 比 template 晚收尾,尾段不被看顧。兩種做法:
- **穩健**:由 `BlueprintPreparer` 在 fork-join 全程自持一個 watchdog 訂在 T1(涵蓋兩分支),並讓
  template 的 `runner.run` 該次**不另起**(避免雙重 / 提早 stop)。
- **最小**:接受「以 template watchdog 盡力涵蓋」,music 尾段失看顧(yt-dlp 下載 hang 另靠 download timeout 兜)。

### 10.7 前端

| | 現況 | 改後 |
|---|---|---|
| 取得進度 | 只 `await POST /generate` 的 response,**不開 WS** | 拿 `job_id` → 開 `WS /ws/progress/{job_id}`(基建已存在,Phase 1 在用)→ 收 STAGE_* |
| 顯示 | 單一「生成中」轉圈 | render template 逐 stage(decode / semantic / whisper / scene / assembly) + music(`music_download` / `music_beats` / `music_lyrics`) |

前端需:(a) 認得新 `stage_name` 並有對應文案,(b) 接受兩分支事件**交錯到達**(非線性 stage 序)。
具體改動需看現有 progress 元件如何 render,未在本文件指定。

### 10.8 風險

| 項目 | 說明 | 風險 |
|---|---|---|
| **`/generate` 同步→async** | 回傳由「blueprint body」改「`{job_id}`」;前端取結果改走 `GET .../blueprint`(磁碟)或 WS `JOB_FINISHED` | 中 — 介面變更,需前後端一起改 |
| **observer 重複累加** | `runner.run` 對注入的 T1 `subscribe` Print/watchdog 後**不 unsubscribe**;同一 T1 被多次 run 注入會累加 → 重複 `[Progress]` 行。generate flow 內 template 只 run 一次,暫不觸發;日後 phase1+phase2 共用同一 T1 需處理 | 中 |
| **併發 emit** | 兩 thread 對同一 T1 `publish` | 低 — `publish` 已 thread-safe(snapshot under lock) |
| **watchdog 涵蓋** | 見 §10.6,music 尾段可能失看顧 | 低/中 — 視採穩健或最小做法 |
| **前端對應** | 新 `stage_name` 需顯示文案、需處理交錯事件 | 中 — 需動前端 |

### 10.9 中途離開 / 重進的韌性(比照 Phase 1)

`launch` 後若使用者**退出 EditorPage 再進來**,要分兩件事:**結果**(已落地、好救)與**即時進度**(需主動接回)。
前提:生成的 worker thread **不受 client 斷線影響**,必跑完並落地(client 取消 / await 取消都中止不了
正在跑的 Python thread)。

**結果救回 —— 已具備,靠磁碟。** `run_workflow` 把最終藍圖寫入 `PHASE4_BLUEPRINT_FILENAME`
(`director_service.py:317`);重進時 EditorPage 走 `GET /projects/{folder}/blueprint`
(`director.py:74` → `load_blueprint`)即可載入。**此路徑與 job/WS 無關,即使超過保留期
(`job_manager` / replay buffer 皆 in-memory、`PROGRESS_JOB_RETENTION_SEC` 後過期)仍有效。**

**即時進度接回 —— 須補,generate 目前缺。** Phase 1 有 `publish_active_job` + `GET .../phase1-progress`
回 `active_phase1_job_id`,讓重整後拿 job_id 重開 WS、`ProgressHub.attach` 補播 + 續傳;**generate 沒有對應品**
(`publish_active_job` 只在 `assets.py`)。要補三件,全部比照 Phase 1:

1. **落地 active generation job_id**:仿 `assets.py:138-161` 的 `job_id_box` 模式 —— `work` 內起點
   `publish_active_generation_job(project_dir, job_id_box["id"])`、`finally` `clear`;`launch` 回傳後同步
   填 box(中間無 await,work 啟動前必填妥)。再加一個查詢端點(或擴充既有 project 詳情)回 `active_generation_job_id`。
2. **generate lock(per user+project,比照 `phase1_lock`)**:按生成前先取鎖;**重進後再按一次 → 偵測到鎖
   已持有 → 回「生成中 + 進行中 job_id」讓前端附掛既有 job,而非 double-run**(否則兩生成併寫
   `PHASE4_BLUEPRINT_FILENAME`,last-writer-wins + 雙倍 GPU)。鎖在 `work` 的 `finally` 釋放。
3. **保留期對齊**:保留期內 → WS replay(`ProgressHub`)+ `GET /jobs/{id}` 皆可;超過 → 退磁碟藍圖兜結果
   (第 1 點查詢端點此時回 `None`,前端據此改載已落地藍圖、不再嘗試 WS)。

| 重進時機 | 即時進度 | 結果 |
|---|---|---|
| 生成已完成 | (無需) | ✅ `GET .../blueprint` 讀磁碟 |
| 生成中、保留期內 | ✅ 查 active job → 重開 WS → replay + 續傳 | 完成後同上 |
| 完成且超過保留期 | ✗ job/buffer 已清(可接受) | ✅ 磁碟藍圖仍在 |

> 結論:**結果韌性現成(磁碟),進度韌性要補 active-job 側通道 + generate lock**。這也回頭證成 §10.2
> 選 `launch`:既然側通道與磁碟落地非建不可,`run_tracked_sync` 的長連線就只剩 timeout 風險、無增益。
