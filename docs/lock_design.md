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

### priority 反餓死（Week 3b 新增）

`acquire(cost_gb, priority)` 多了 `priority`:**只要有高優先(Qwen,`INFERENCE_PRIORITY>0`)在等,
低優先(其餘模型恆 0)一律不放行** —— 讓在飛的小 forward 排空、預算騰給 Qwen,避免 MUSIQ/LAION
串流把主瓶頸 Qwen 的大塊請求無限延後。子類用 class 屬性 `INFERENCE_PRIORITY` 宣告,`inference_guard`
經 `gate.acquire(self.INFERENCE_VRAM_COST_GB, self.INFERENCE_PRIORITY)` 帶入。

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

要支援這個結構需要兩個基礎變動:
- `BaseModelManager` singleton key 從 `device_id` 改 `(device_id, slot_id)` tuple
- `ModelPool` 介面從 `gpu_ids: list[int]` 改 `slots: list[GpuSlot]`(`gpu_ids` 保留為 backward-compat alias)

**Week 1 結構就緒,但 BinaryGate 下同卡兩 instance forward 仍會被 L2 序列化,
紅利要等 Week 3b BudgetGate 才現**。

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
| MediaPipe | `cpu` | skip | ✓ |
| Saliency(rembg)、VAD(silero) | 內部管理,不設 self.device | skip | ✓ |
| Gemini API | 無 device attribute | skip | ✓ |

子類別零改動。

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

*文件最後更新:2026-06-03(Week 3b:BudgetGate 實作 + priority 反餓死 + gate factory 簽名帶 device_id)*
