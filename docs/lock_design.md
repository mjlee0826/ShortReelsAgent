# Lock 設計:GPU 多模型併發控制

> 本文件說明 Pipeline 在 GPU 上跑多個 model 時用的鎖層級、不可省略的反例、
> 以及 Week 1 → Week 3b 的升級路徑。
> 由 `integrated_acceleration_plan.md` Layer 1/2 衍生,聚焦在 model 層併發。

---

## 1. 三層鎖 + 一個 async 機制

整套設計**只有三層真鎖**,順序固定 `L1 → L2 → L3`,**結構上不可能 deadlock**。

| 層 | 對象 / 粒度 | 職責 | Week 啟用 |
|---|---|---|---|
| **L1** ModelPool Borrow Queue | 每個 model class 一個 pool | 把 instance **公平分派**給多個 driver thread,確保同一 instance 不雙借 | Week 2a |
| **L2** GpuGate (per-device) | 每張 GPU 一個 gate | 同卡 forward 互斥(Week 1 BinaryGate)或 VRAM 預算控制(Week 3b BudgetGate) | Week 1 |
| **L3** Inference Lock (per-instance) | 每個 Manager singleton 一個 | 同 instance 不可重入,保護 `generate()` 內部狀態與 `empty_cache()` | 既有 |

BatchCollector(Week 3a)是 producer-consumer queue + Future dispatch,
**不持有 inference 鎖**,不算鎖層;forward 仍走 L1→L2→L3。

---

## 2. 為什麼三層都不能省

每層都有「沒它就會出事」的場景。

### 沒 L2 → 同卡跨 model 撞 VRAM(現有 bug)

```
GPU0 同時放 Qwen + Whisper
thread A → qwen.analyze()        持 qwen._inference_lock (L3)
thread B → whisper.transcribe()  持 whisper._inference_lock (L3)
              ↑ L3 是 per-instance,兩個鎖完全獨立 → 兩條 forward 同時跑 → OOM
```
L3 無能,**L2 才能跨 instance 互斥**。

### 沒 L1 → driver 全擠 GPU0,GPU1 閒置

```
4 driver thread 都打 QwenManager().analyze()
QwenManager() 預設 device_id=0 → 全部擠 GPU0
GPU0 排隊 4 條,GPU1 完全閒置
```
L2 只做互斥不做分派,**L1 ModelPool.borrow() 才能把 driver 分散到所有 GPU**。

### 沒 L3 → 繞過 Pool 的呼叫路徑(測試 / CLI / 舊程式碼)雙進入

```
# 沒走 Pool 的直接呼叫(Week 1 結束時 director_service 還是這條路徑)
thread A → QwenManager().analyze()    # 取得 singleton
thread B → QwenManager().analyze()    # 同個 singleton
              ↑ L1 不在路徑上,L3 是唯一防線
              ↑ 同 instance 不可重入(KV cache、empty_cache 競爭)
```
L1 只保護「走 Pool」的路徑,**L3 是 instance level 的最後防線**。

---

## 3. L1 / L2 常見混淆點

|  | 同一 instance 多 thread | 同卡不同 instance 多 thread |
|---|---|---|
| **L1 ModelPool** | ✓ 互斥(借出後不再借) | ✗ 不處理(不同 model 各自 pool 不知情) |
| **L2 GpuGate** | ✓ 互斥(同卡 forward 鎖) | ✓ 互斥(關鍵保護點) |

L1 解決「**負載分配 + 同 instance 互斥**」,L2 解決「**同卡跨 instance 互斥**」,**兩者正交不可互替**。

---

## 4. GpuGate Strategy Pattern + 升級路徑

GpuGate 設計成 Strategy 物件,Week 1 預設 BinaryGate(粗,序列化同卡),
Week 3b 升級成 BudgetGate(細,看 VRAM cost),**Manager 子類零改動**。

### Week 1 BinaryGate

```
GPU_GATES[0] = BinaryGate (semaphore=1)
thread X: GPU_GATES[0].acquire() ✓ forward
thread Y: GPU_GATES[0].acquire() ✗ 阻塞等 X 完成
```
保證同卡一次最多一條 forward。**代價:VRAM 夠也只能序列**。

### Week 3b BudgetGate（✅ 已實作）

```
GPU_GATES[0] = BudgetGate(total=24GB, buffer=1.5GB)   # total = free − 已常駐權重
thread X: acquire(cost=4, prio=0)  ✓ used=4
thread Y: acquire(cost=3, prio=0)  ✓ used=7   ← 同卡並行!
thread Z: acquire(cost=18,prio=0)  ✗ block,預算不夠
          ↓ X release
thread Z: acquire(cost=18,prio=0)  ✓ used=21
```
**VRAM 夠時同卡併發,夠不夠由 cost 決定**;`cost > 整卡預算` 時於 `in_flight==0` 仍單獨放行(避免永久阻塞)。

### priority 反餓死（Week 3b 新增；✅ 2026-06-05 軟化為「保留車道」）

`acquire(cost_gb, priority)` 多了 `priority`,讓主瓶頸 Qwen(`INFERENCE_PRIORITY=10`)在等大塊 VRAM 時,
不被 MUSIQ/LAION/AudioEnv/Whisper 等小模型(恆 0)的串流無限延後。子類用 class 屬性 `INFERENCE_PRIORITY`
宣告,`inference_guard` 經 `gate.acquire(self.INFERENCE_VRAM_COST_GB, self.INFERENCE_PRIORITY)` 帶入。

> **⚠️ 2026-06-05 修正(原硬規則反把小模型餓死,已軟化)**:最初版是「**只要有高優先在等,低優先一律不放行**」,
> 但 Qwen 單次 forward 長達數十秒~數分鐘時,同卡小模型被整場餓死(log 裡 aes 實算 ~50ms 卻被卡到 91s)。
> 改為**保留一條低優先車道**:即使有 Qwen 在等,只要低優先「在飛成本總和 ≤ budget ×
> `BUDGET_GATE_LOW_PRIORITY_RESERVE_RATIO`(預設 0.5)」仍放行(且整體不超預算防 OOM),
> 讓小模型細水長流、Qwen 仍對大半預算保有優先權。`0.0`=回到舊硬餓死規則、`1.0`=等同取消優先序。

### 一行升級（實際簽名帶 device_id）

```python
# Week 3b GpuCapacityManager.apply() 啟動時(每卡 free 不同 → per-device 預算):
BaseModelManager.register_gate_factory(
    lambda device_id: BudgetGate(
        total_gb=per_device_budget[device_id],   # = 該卡 free − 已放置常駐權重
        safety_buffer_gb=1.5,
    )
)
```
工廠簽名為 `Callable[[int], GpuGate]`(收 `device_id`,`BinaryGate` 忽略);全域 L2 替換,
所有 Manager 子類繼續用 `inference_guard()`,零修改。`INFERENCE_VRAM_COST_GB` 須填**forward 暫態峰值**
(非常駐權重);常駐權重已在 `total_gb` 扣除,填錯成權重會重複扣、gate 過度保守。

### OOM 容錯:同卡重試 + 跨卡 failover（✅ Week 3b）

兩層分工,對應「瞬時 OOM」與「持續 OOM」:

- **同卡瞬時 OOM** → `@oom_resilient` 裝飾器(套 `@synchronized_inference` **外層**):catch CUDA OOM →
  鎖外 `empty_cache()` + 線性 backoff → 重試 ≤ N(`OOM_RETRY_MAX_ATTEMPTS`),耗盡 re-raise。每次重試都
  重新取 L2/L3,給同卡其他 forward / 鄰居 process 排空時間。GPU manager 的 broad except 前先
  `if is_cuda_oom(e): raise`,不再把 OOM 吞成 null object。
- **同卡持續 OOM(鄰居佔住該卡)** → `ModelPool.run_with_failover(fn)`:同卡重試無效時**改借不同 device
  的 instance** 重試,直到成功或試完所有不同卡。換卡發生在 L1(借出層),與 `oom_resilient`(同卡)分工互補。
  semantic(Qwen)/ saliency / 各 batch_fn 都走這條;單卡 pool 自動退化為單次借出(無回歸)。

---

## 5. 同卡多 instance Pool 結構

預設 `ModelPool(model_class, gpu_ids=[0, 1])` 配置每張卡一份。
VRAM 富裕(或 Week 3b 後)可配同卡多 instance:

```python
qwen_pool = ModelPool(QwenManager, slots=[
    GpuSlot(device_id=0, slot_id=0),
    GpuSlot(device_id=0, slot_id=1),  # 同卡第二份 weight
    GpuSlot(device_id=1, slot_id=0),
])
```

要支援這個結構需要兩個基礎變動(Week 1 已備):
- `BaseModelManager` singleton key 從 `device_id` 改 `(device_id, slot_id)` tuple
- `ModelPool` 介面從 `gpu_ids: list[int]` 改 `slots: list[GpuSlot]`(`gpu_ids` 保留為 backward-compat alias)

**✅ Week 3b 起由 `GpuCapacityManager` 自動規劃 slots,呼叫端不必手填**:
- **Qwen**:依該卡 free VRAM 自動算同卡份數(`QWEN_MAX_SLOTS_PER_GPU`:`0`=auto 取「能真正並行的份數」
  = `floor((free−小模型常駐−buffer)/(resident+transient))`、`>0`=上限)。BudgetGate(非 BinaryGate)下
  同卡多 instance 才真的能並行 forward —— 紅利現了。
- **~~Saliency:以 per-model 上限 `1` 做每卡一份的多卡分散~~** → **⚠️ 2026-06-05 起已移出 GPU、改純 CPU pool**
  (見 §7 更正);GpuCapacityManager 不再規劃 Saliency 的 GPU slot,`max_slots_by_model={Saliency:1}` 已失效。
- 規劃會避免把瀕死卡塞爆(放不下「常駐+暫態+buffer」就不放),並把單卡小模型集中到「最不排擠 Qwen lane」的卡。

---

## 6. 三條主要呼叫路徑

### Path A:Singleton 直接呼叫(Week 1 結束後仍存在)

```
driver thread
  → manager = QwenManager()
  → manager.analyze_media(...)
       └─ @synchronized_inference
            └─ with self.inference_guard():
                 ├─ L2: GPU_GATES[device_id].acquire()
                 │    └─ L3: self._inference_lock
                 │         └─ forward()
```

### Path B:ModelPool 多 GPU(Week 2a 啟用)

```
driver thread
  → with model_pool.borrow() as q:        # L1
       → q.analyze_media(...)
            └─ inference_guard:
                 ├─ L2: GPU_GATES[q._device_id].acquire()
                 │    └─ L3: q._inference_lock
                 │         └─ forward()
```

### Path C:BatchCollector(Week 3a 啟用,async 不是鎖)

```
driver A/B/C/D → collector.submit(item) → future.wait()
                         ↑ queue.Queue 內部 thread-safe,非鎖

BatchCollector worker thread(達 batch_size 或 timeout_ms):
  → with model_pool.borrow() as m:       # L1
       → m.score_batch([items])           # @synchronized_inference
            └─ inference_guard → L2 → L3 → forward(stacked batch)
  → split results → future.set_result(r) for r in ...
  → driver A/B/C/D 各自 wake
```

---

## 7. CPU / 雲端 API 模型自動跳過 L2

`BaseModelManager.inference_guard()` 依 `self.device` 判斷:
- `cuda*` → 走 L2 GpuGate
- `cpu` / 無 device attribute → 跳過 L2,只取 L3

| 模型 | self.device | L2 | L3 |
|---|---|---|---|
| Qwen / Whisper / MUSIQ / LAION / AudioEnv | `cuda:N` | ✓ | ✓ |
| **Saliency**(rembg/onnxruntime/U²-Net) | `cpu`(**2026-06-05 起改純 CPU pool**,見下方更正) | skip | ✓ |
| **MediaPipe** | `cpu`(CPU pool,每 asset 一份) | skip | ✓ |
| **VAD**(silero) | `cpu`(**2026-06-05 起改 CPU pool**,多 instance 真平行) | skip | ✓ |
| Gemini API | 無 device attribute | skip | ✓ |

> **⚠️ 更正一(Week 3b,已被更正二推翻)**:Saliency 原本「內部管理、不設 device → 跳過 L2」,在共用機上
> onnxruntime 會自選 cuda:0、不受 BudgetGate 控管而 hang。Week 3b 曾改為綁「最空卡」cuda:N + 納入 capacity/BudgetGate。
>
> **⚠️ 更正二(2026-06-05,最終定案,推翻更正一)**:綁 GPU 後**實機在共用工作站仍出事**——onnxruntime
> `CUDAExecutionProvider` 與 PyTorch 各自的 CUDA allocator / context 互不知情,共卡時偶發 hang / OOM。
> 最終**直接移出 GPU、固定 `CPUExecutionProvider`**(`self.device='cpu'` → 跳過 L2、borrow 即時放行),
> 改由 `model_pool_registry` 的獨立 **CPU pool**(`SALIENCY_POOL_SIZE` 份獨立 onnxruntime CPU session)管併發;
> CPU EP 推論釋放 GIL,根除上述故障。**VAD 同期也從 CPU 單例改 CPU pool**(`VAD_POOL_SIZE` 份獨立 Silero,
> 修正單例 `@synchronized_inference` 把多影片 VAD 序列化到 250s+);MediaPipe 亦為 CPU pool。三池同構、皆啟動期預熱。

---

## 8. Deadlock 不可能性

四個 deadlock 條件:

| 條件 | 本設計 |
|---|---|
| Mutual Exclusion | 成立 |
| Hold and Wait | 成立 |
| No Preemption | 成立 |
| **Circular Wait** | **不成立** — 全域偏序 L1 < L2 < L3,所有路徑一致 |

破壞 Circular Wait → **結構上不可能 deadlock**。

**設計約定**:推論路徑內部禁止重入 ModelPool(若持 L3 期間再借另一 model
會違反偏序)。本專案目前無此路徑。

---

*文件最後更新:2026-06-05(模型換代後續修正:Saliency **移出 GPU 改純 CPU pool**(推翻 6-04 的綁卡)、
VAD 改 CPU pool、MediaPipe CPU pool、BudgetGate priority **軟化為保留車道**(反餓死))*
*前版:2026-06-04(Week 3b 後續:Saliency 納入 capacity/BudgetGate、VAD 顯式 CPU、同卡多 instance 由 capacity 自動規劃、OOM 同卡重試 + 跨卡 failover)*
*前版:2026-06-03(Week 3b:BudgetGate + priority 反餓死 + gate factory 簽名帶 device_id)*
