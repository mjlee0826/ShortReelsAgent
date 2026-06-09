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

> 步驟 1、2 即使不做 3 也各自有價值(去重 + 根治 VRAM 撞車),3 才是並行加速。

**warmup 解耦(§6)獨立於上述**:不依賴 1–4、可隨時單獨落地,且改動小(三處)。
建議優先做,先消掉 import 副作用(W1)與 import-期 warmup 推不出進度(W4),再進 1–4。
