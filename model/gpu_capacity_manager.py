"""
GpuCapacityManager：啟動時掃描各 GPU free VRAM，規劃模型放置 + 每卡 BudgetGate 預算 (Week 3b)。

職責 (plan §5.3)
----------------
- **掃描** —— 用 ``torch.cuda.mem_get_info`` 取每張卡的 free / total VRAM（掃描函式可注入假值供測試）。
- **規劃放置** —— 依「eager 優先序 + check-before-load」決定每個模型放哪些 ``(device, slot)``：
  Qwen（主瓶頸）優先且盡量鋪滿可放下的每張卡（多卡）；其餘小模型用剩餘 VRAM 挑最寬鬆的卡放單份；
  放不下的降級 lazy（borrow 時再嘗試）。
- **算預算** —— 每卡 BudgetGate 的 ``total_gb = free − 已放置常駐權重總和``（Gate 再扣 ``GPU_SAFETY_BUFFER_GB``）。
- **套用** —— :meth:`apply` 以 ``BaseModelManager.register_gate_factory`` 一行把全域 L2 換成 per-device
  ``BudgetGate``（Manager 子類零改動）。

設計模式
--------
- **Strategy 注入**：``profiles`` / ``eager_order`` / ``multi_card_models`` / ``mem_scan`` 皆可注入，
  讓本類別在無 GPU、無重依賴的環境也能做純邏輯單元測試（不必真載入 transformers/pyiqa/panns）。
- **Lazy Default**：未注入時才 lazy import 各 Manager 類別組預設規格，避免「import 本模組就拉重依賴」。
- **Value Object**：``ModelVramProfile`` / ``CapacityPlan`` 為 frozen dataclass。

為什麼放在 model/ 層
--------------------
本類別只依賴 ``model/`` 內元件（BaseModelManager / BudgetGate / GpuSlot）與 ``config/``，
**不依賴 ``media_processor/pipeline``**，維持「pipeline → model」單向依賴；GPU 偵測在此自帶極簡實作
（不 import pipeline 的 gpu_detect），由 ``ModelPoolRegistry`` 呼叫端傳入或自動偵測。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from config.media_processor_config import (
    GPU_SAFETY_BUFFER_GB,
    QWEN_MAX_SLOTS_PER_GPU,
    QWEN_RESIDENT_VRAM_GB,
    QWEN_TRANSIENT_VRAM_GB,
    WHISPER_RESIDENT_VRAM_GB,
    WHISPER_TRANSIENT_VRAM_GB,
    MUSIQ_RESIDENT_VRAM_GB,
    MUSIQ_TRANSIENT_VRAM_GB,
    LAION_RESIDENT_VRAM_GB,
    LAION_TRANSIENT_VRAM_GB,
    AUDIO_ENV_RESIDENT_VRAM_GB,
    AUDIO_ENV_TRANSIENT_VRAM_GB,
    SALIENCY_RESIDENT_VRAM_GB,
    SALIENCY_TRANSIENT_VRAM_GB,
)
from model.base_model_manager import BaseModelManager
from model.gpu_gate import BudgetGate
from model.model_pool import GpuSlot

# bytes → GB 換算（mem_get_info 回 bytes）
_BYTES_PER_GB = 1024 ** 3
# 無 GPU 時的 CPU 後備裝置 id（經 get_device_str 對應到 'cpu'）
_CPU_FALLBACK_DEVICE_ID = 0
# 預設槽位 id（同卡單一實例）
_DEFAULT_SLOT_ID = 0


@dataclass(frozen=True)
class ModelVramProfile:
    """單一模型的 VRAM 估值 (Value Object)。

    - ``resident_gb``：常駐權重（載入後一直佔著），決定一張卡放得下幾份模型。
    - ``transient_gb``：單次 forward 暫態峰值（activation/KV cache/workspace），即 BudgetGate 記帳成本。
    """

    resident_gb: float
    transient_gb: float


@dataclass(frozen=True)
class CapacityPlan:
    """一次容量規劃的結果 (Value Object)。"""

    # 每個模型類別 → 規劃放置的槽位列表（空 = 未 eager 放置）
    slots_by_model: dict[type, list[GpuSlot]]
    # 每卡 BudgetGate 的 total_gb（= free − 已放置常駐權重；Gate 內部再扣 safety buffer）
    budget_by_device: dict[int, float]
    # 規劃為 eager 預載且放得下的模型（依優先序）
    eager_models: tuple[type, ...]
    # 放不下、降級為 lazy（on-demand 才建 pool）的模型
    lazy_models: frozenset[type]
    # 本次規劃涵蓋的 GPU id（空 = 無 CUDA）
    gpu_ids: tuple[int, ...]
    # plan 當下掃到的每卡 free / total VRAM（GB），供啟動佈局報表顯示（預設空字典向後相容）
    free_by_device: dict[int, float] = field(default_factory=dict)
    total_by_device: dict[int, float] = field(default_factory=dict)


class GpuCapacityManager:
    """掃描 free VRAM、規劃模型放置與每卡預算，並把 L2 Gate 換成 per-device BudgetGate。"""

    def __init__(
        self,
        gpu_ids: Optional[list[int]] = None,
        profiles: Optional[dict[type, ModelVramProfile]] = None,
        multi_card_models: Optional[set[type]] = None,
        eager_order: Optional[list[type]] = None,
        safety_buffer_gb: float = GPU_SAFETY_BUFFER_GB,
        max_slots_per_gpu: int = QWEN_MAX_SLOTS_PER_GPU,
        max_slots_by_model: Optional[dict[type, int]] = None,
        mem_scan: Optional[Callable[[int], tuple[float, float]]] = None,
    ):
        """
        準備規劃所需的裝置清單、模型規格與掃描函式（規劃延遲到首次 :meth:`plan`）。

        Args:
            gpu_ids: 明示裝置清單（主要供測試 / 呼叫端傳入）；``None`` 時自動偵測 CUDA。
            profiles / multi_card_models / eager_order: 模型規格；任一為 ``None`` 時才 lazy 組預設值
                （預設值需 import 各 Manager 類別，故注入完整三者即可完全避開重依賴）。
            safety_buffer_gb: 每卡預留給系統 / 鄰居的 VRAM。
            max_slots_per_gpu: 多卡模型「同卡 instance 份數」的**預設**上限（主要給 Qwen）；``0``（預設）
                = 依該卡 free VRAM 自動算可並行份數，``>0`` = 取 min(本值, 自動值)。對應 config ``QWEN_MAX_SLOTS_PER_GPU``。
            max_slots_by_model: per-model 覆寫上限（例如 ``{SaliencyManager: 1}`` 表示「每卡剛好一份」）；
                未列入者用 ``max_slots_per_gpu``。``None`` 時用預設規格內建的對照（注入完整規格時為空）。
            mem_scan: ``device_id → (free_gb, total_gb)`` 掃描函式；``None`` 時用真 ``mem_get_info``。
        """
        self._gpu_ids = list(gpu_ids) if gpu_ids is not None else self._detect_cuda_ids()
        # 任一規格缺失才 lazy 組預設（避免測試注入時仍 import 重依賴）
        default_max_slots: dict[type, int] = {}
        if profiles is None or multi_card_models is None or eager_order is None:
            specs = self._default_model_specs()
            default_profiles = {c: ModelVramProfile(r, t) for c, r, t, _m, _ms in specs}
            default_order = [c for c, _r, _t, _m, _ms in specs]
            default_multi = {c for c, _r, _t, m, _ms in specs if m}
            # 只收「有特殊上限（ms>0）」的多卡模型，例如 Saliency=1；Qwen（ms=0）落到 _max_slots_per_gpu
            default_max_slots = {c: ms for c, _r, _t, m, ms in specs if m and ms > 0}
        self._profiles = profiles if profiles is not None else default_profiles
        self._eager_order = eager_order if eager_order is not None else default_order
        self._multi_card = multi_card_models if multi_card_models is not None else default_multi
        self._buffer = safety_buffer_gb
        self._max_slots_per_gpu = max_slots_per_gpu
        # per-model 每卡上限覆寫表（Saliency=1 等）；未列入者 _place_model 會回退 _max_slots_per_gpu
        self._max_slots_by_model = (
            max_slots_by_model if max_slots_by_model is not None else default_max_slots
        )
        self._mem_scan = mem_scan or self._real_mem_scan
        # 規劃結果快取（首次 plan 計算後固定，跨 get_pool / apply 共用同一份）
        self._plan: Optional[CapacityPlan] = None
        self._lock = threading.Lock()

    # ── 對外介面 ─────────────────────────────────────────────────────────────

    def plan(self) -> CapacityPlan:
        """回傳容量規劃（首次呼叫時掃描 + 計算並快取，之後回同一份）。"""
        if self._plan is not None:
            return self._plan
        with self._lock:
            if self._plan is None:
                self._plan = self._compute_plan()
        return self._plan

    def plan_slots(self, model_class: type) -> list[GpuSlot]:
        """
        回傳指定模型要鋪的槽位（給 ``ModelPoolRegistry`` 建 ``ModelPool``）。

        eager 放置過的模型回其規劃槽位；未規劃（lazy 或不在 profile）的回退到「預算最寬鬆的卡」
        單一槽位（無 GPU 時回退 CPU），讓 pool 仍可運作、borrow 時再以即時 VRAM 重檢守門。
        """
        current = self.plan()
        slots = current.slots_by_model.get(model_class)
        if slots:
            return list(slots)
        return [self._fallback_slot(current)]

    def get_pool_size(self, model_class: type) -> int:
        """回傳指定模型規劃的槽位數（roadmap §8 對 ModelPoolRegistry 的介面）。"""
        return len(self.plan_slots(model_class))

    def transient_gb(self, model_class: type) -> float:
        """回傳指定模型的 forward 暫態成本（給 ModelPool.borrow 做即時 VRAM 重檢用）；未知回 0。"""
        profile = self._profiles.get(model_class)
        return profile.transient_gb if profile is not None else 0.0

    def is_eager(self, model_class: type) -> bool:
        """指定模型是否規劃為 eager 預載（放得下）。"""
        return model_class in self.plan().eager_models

    def eager_models(self) -> tuple[type, ...]:
        """依優先序回傳規劃為 eager 預載的模型清單（供 ModelPoolRegistry warm up）。"""
        return self.plan().eager_models

    def apply(self) -> None:
        """
        把全域 L2 Gate 換成 per-device ``BudgetGate``（依各卡預算）。

        無 CUDA 時 no-op（維持預設 BinaryGate，CPU 模型本就跳過 L2）。
        """
        current = self.plan()
        if not current.gpu_ids:
            print("[GpuCapacityManager] 無 CUDA 裝置，維持預設 BinaryGate（不套 BudgetGate）")
            return

        # 以 plan 當下的每卡預算建立工廠；閉包捕捉 budget / buffer，依 device_id 給對應預算
        budget = dict(current.budget_by_device)
        buffer = self._buffer

        def factory(device_id: int) -> BudgetGate:
            """依卡別建立帶該卡預算的 BudgetGate（未知卡給 0 → 僅允許 in_flight==0 單獨跑）。"""
            return BudgetGate(total_gb=budget.get(device_id, 0.0), safety_buffer_gb=buffer)

        BaseModelManager.register_gate_factory(factory)
        print(f"[GpuCapacityManager] 已套用 per-device BudgetGate；{self.describe()}")

    def describe(self) -> str:
        """回傳規劃摘要字串（供啟動日誌；對應驗收條件「Qwen 只放某些卡」可肉眼確認）。"""
        current = self.plan()
        if not current.gpu_ids:
            return "GpuCapacityManager(no CUDA)"
        placements = ", ".join(
            f"{cls.__name__}→{[f'cuda:{s.device_id}#{s.slot_id}' for s in slots]}"
            for cls, slots in current.slots_by_model.items()
        )
        budgets = {d: round(b, 2) for d, b in current.budget_by_device.items()}
        lazy = sorted(c.__name__ for c in current.lazy_models)
        qwen_slots = "auto" if self._max_slots_per_gpu <= 0 else self._max_slots_per_gpu
        return (
            f"GpuCapacityManager(gpu_ids={list(current.gpu_ids)}, "
            f"qwen_max_slots/gpu={qwen_slots}, "
            f"budget_gb(扣常駐後,Gate 再扣 buffer {self._buffer})={budgets}, "
            f"placements=[{placements}], lazy={lazy})"
        )

    def device_rows(self) -> list[tuple[int, float, float, float]]:
        """每卡 VRAM 報表列：``(device_id, total_gb, plan時free_gb, BudgetGate total預算_gb)``。"""
        current = self.plan()
        return [
            (
                dev,
                current.total_by_device.get(dev, 0.0),
                current.free_by_device.get(dev, 0.0),
                current.budget_by_device.get(dev, 0.0),
            )
            for dev in current.gpu_ids
        ]

    def placement_rows(self) -> list[tuple[str, list[str], float, str]]:
        """模型放置報表列：``(模型名, [slot 字串], 單份常駐_gb, 'eager'|'lazy')``，eager 在前。"""
        current = self.plan()
        rows: list[tuple[str, list[str], float, str]] = []
        for model_class, slots in current.slots_by_model.items():
            slot_strs = [f"cuda:{s.device_id}#{s.slot_id}" for s in slots]
            resident = self._profiles[model_class].resident_gb if model_class in self._profiles else 0.0
            rows.append((model_class.__name__, slot_strs, resident, "eager"))
        for model_class in sorted(current.lazy_models, key=lambda c: c.__name__):
            resident = self._profiles[model_class].resident_gb if model_class in self._profiles else 0.0
            rows.append((model_class.__name__, [], resident, "lazy"))
        return rows

    # ── 規劃核心 ─────────────────────────────────────────────────────────────

    def _compute_plan(self) -> CapacityPlan:
        """掃描 free VRAM → 依優先序 check-before-load 放置 → 算每卡剩餘預算。"""
        gpu_ids = self._gpu_ids
        if not gpu_ids:
            # 無 GPU：空計畫，所有模型視為 lazy（實際走 CPU 後備槽位）
            return CapacityPlan({}, {}, tuple(), frozenset(self._profiles), tuple())

        # 先存「plan 當下」每卡 (free, total) 掃描值；remaining 由 free 起算、放置時逐步扣除
        scan = {dev: self._mem_scan(dev) for dev in gpu_ids}
        remaining = {dev: scan[dev][0] for dev in gpu_ids}
        slots_by_model: dict[type, list[GpuSlot]] = {}
        eager: list[type] = []
        lazy: set[type] = set()

        # 單卡小模型「集中放」的卡：選放它最不排擠 Qwen lane 的卡（通常 = 最緊但放得下的卡），
        # 而非最空的卡。動機：小模型只 ~5.5GB，放最空的大卡會白白吃掉那張一整條 Qwen lane（10.5GB）；
        # 改塞進「緊、但小模型剛好填進其放不滿一條 lane 的零頭」的卡，最空的大卡就能整張拿去放 Qwen。
        small_host = self._choose_small_host(gpu_ids, {dev: scan[dev][0] for dev in gpu_ids})

        # 依 eager 優先序逐一放置：Qwen 在最前且多卡，先把它的常駐位置佔走
        for model in self._eager_order:
            profile = self._profiles[model]
            placed = self._place_model(model, profile, gpu_ids, remaining, small_host)
            if placed:
                slots_by_model[model] = placed
                eager.append(model)
            else:
                lazy.add(model)

        budget_by_device = {dev: max(0.0, remaining[dev]) for dev in gpu_ids}
        return CapacityPlan(
            slots_by_model=slots_by_model,
            budget_by_device=budget_by_device,
            eager_models=tuple(eager),
            lazy_models=frozenset(lazy),
            gpu_ids=tuple(gpu_ids),
            free_by_device={dev: scan[dev][0] for dev in gpu_ids},
            total_by_device={dev: scan[dev][1] for dev in gpu_ids},
        )

    def _place_model(
        self,
        model: type,
        profile: ModelVramProfile,
        gpu_ids: list[int],
        remaining: dict[int, float],
        small_host: int,
    ) -> list[GpuSlot]:
        """
        為單一模型挑槽位並就地扣除 remaining（check-before-load）。

        - 多卡模型（Qwen）：每張卡依 free VRAM 算同卡份數；只有 ``small_host``（小模型會落腳的卡）
          才預留小模型常駐，其餘卡整張拿去算 Qwen 份數（最大化空卡的 Qwen 並行）。
        - 單卡模型：挑剩餘最寬鬆且放得下的卡放單份。
        放不下回空列表（→ lazy）。``buffer`` 留作不被任何模型常駐佔用的頭空間。
        """
        need = profile.resident_gb + self._buffer
        if model in self._multi_card:
            # 多卡模型：每張卡依 free VRAM 算同卡份數。max_slots 為 per-model 上限
            # （Qwen=全域；Saliency=1 → 每卡一份）。
            placed = []
            max_slots = self._max_slots_by_model.get(model, self._max_slots_per_gpu)
            for dev in gpu_ids:
                count = self._multi_card_slot_count(
                    profile, remaining[dev], reserve_small=(dev == small_host), max_slots=max_slots
                )
                for slot_id in range(count):
                    placed.append(GpuSlot(device_id=dev, slot_id=slot_id))
                    # 每份各扣一份常駐權重；buffer 是保留頭空間，不從預算實扣
                    remaining[dev] -= profile.resident_gb
            return placed

        # 單卡模型：優先集中放到 small_host（最不排擠 Qwen 的緊卡），放不下才退回 best-fit
        if remaining[small_host] >= need:
            remaining[small_host] -= profile.resident_gb
            return [GpuSlot(device_id=small_host, slot_id=_DEFAULT_SLOT_ID)]
        candidates = [dev for dev in gpu_ids if remaining[dev] >= need]
        if not candidates:
            return []
        best = max(candidates, key=lambda dev: remaining[dev])
        remaining[best] -= profile.resident_gb
        return [GpuSlot(device_id=best, slot_id=_DEFAULT_SLOT_ID)]

    def _choose_small_host(self, gpu_ids: list[int], free_by_dev: dict[int, float]) -> int:
        """
        選「單卡小模型集中放」的卡：放這張卡損失最少 Qwen lane（通常 = 最緊但放得下小模型的卡）。

        為什麼不是最空的卡：小模型只 ~5.5GB，放最空的大卡會白白佔掉那張卡一整條 Qwen lane（10.5GB）；
        改放到「小模型剛好塞進其放不滿一條 lane 的零頭」的卡，幾乎不損失 Qwen lane，最空的大卡
        就能整張拿去放 Qwen。

        規則：在「放得下全部小模型（+buffer）」的卡中，挑「當 small_host 時被排擠掉的 Qwen lane 數」
        最小者；平手取較緊（free 較小）的，把空卡留給 Qwen。沒有卡放得下全部小模型時退回最空卡（盡力）。
        """
        small_total = self._single_card_resident_total()
        multi = [m for m in self._eager_order if m in self._multi_card]
        # 沒有多卡模型 / 沒有單卡模型 → small_host 不影響 Qwen 規劃，回最空卡（維持簡單）
        if not multi or small_total <= 0:
            return max(gpu_ids, key=lambda dev: free_by_dev[dev])
        qwen_class = multi[0]
        qwen_profile = self._profiles[qwen_class]
        qwen_max_slots = self._max_slots_by_model.get(qwen_class, self._max_slots_per_gpu)
        # 放得下全部小模型（+buffer）的卡才有資格當 host；都放不下則退回最空卡盡力
        candidates = [dev for dev in gpu_ids if free_by_dev[dev] >= small_total + self._buffer]
        if not candidates:
            return max(gpu_ids, key=lambda dev: free_by_dev[dev])

        def displaced_lanes(dev: int) -> int:
            """放小模型在此卡會被排擠掉的 Qwen lane 數（不預留 vs 預留小模型的 lane 差）。"""
            free = free_by_dev[dev]
            return (
                self._multi_card_slot_count(qwen_profile, free, reserve_small=False, max_slots=qwen_max_slots)
                - self._multi_card_slot_count(qwen_profile, free, reserve_small=True, max_slots=qwen_max_slots)
            )

        # 損失最少 Qwen lane 者；平手取較緊（free 較小）的卡，把空卡留給 Qwen
        return min(candidates, key=lambda dev: (displaced_lanes(dev), free_by_dev[dev]))

    def _multi_card_slot_count(
        self, profile: ModelVramProfile, free_on_dev: float, reserve_small: bool, max_slots: int
    ) -> int:
        """
        算多卡模型在單張卡上要放幾份 instance（同卡多 slot）。

        每條「能真正並行的 lane」需 resident（常駐權重）+ transient（forward 暫態）才有意義：
        只塞得下額外 resident、塞不下其 transient 的 instance 只會在 L2 BudgetGate 空等，純浪費 VRAM。

        ``reserve_small``：此卡是否為「小模型會落腳的卡」（small_host）。
        - True：預留所有單卡模型常駐，避免多卡 slot 擠掉小模型 / 撐爆同卡併發暫態預算。
        - False：小模型不會放這張，整張拿去算份數（解掉空卡只放得下 1 份的浪費）。

        ``max_slots``：per-model 每卡上限。``0`` = 自動（依 VRAM 算可並行份數，Qwen 用）；
        ``>0`` = 取 min 當上限（Saliency=1 → 每卡剛好一份）。
        自動份數 = ``floor((free − 預留 − buffer) / (resident + transient))``。
        """
        # 只有 small_host 卡預留小模型常駐；其餘卡 reserve=0，整張算份數
        reserve = self._single_card_resident_total() if reserve_small else 0.0
        per_lane = profile.resident_gb + profile.transient_gb  # 一條可並行 lane 的 VRAM 足跡
        # 硬條件：扣掉要預留的小模型後，要放得下「常駐 + 一次 forward 暫態 + buffer」才放 Qwen。
        # 只塞得下權重、塞不下暫態的卡（尤其共用機被鄰居佔走 VRAM 的卡）放了也跑不動 → forward
        # 直接 OOM/hang，故不放（回 0、降 lazy / 改放別卡）。這也移除了舊「min-1 強制至少 1 份」
        # 在瀕死卡上硬塞一個跑不動的 Qwen 的問題（實機共用 GPU hang 的根因之一）。
        if free_on_dev - reserve < per_lane + self._buffer:
            return 0
        usable = free_on_dev - reserve - self._buffer
        # 硬條件已保證 usable ≥ per_lane → useful ≥ 1（不再需要 max(1,...) 硬撐）
        useful = int(usable // per_lane) if per_lane > 0 else 1
        # per-model 上限（>0）再夾；≤0 為自動不夾
        if max_slots > 0:
            return min(max_slots, useful)
        return useful

    def _single_card_resident_total(self) -> float:
        """單卡模型（非多卡）的常駐權重總和：多卡模型同卡多 slot 時要預留的共存空間。"""
        return sum(
            prof.resident_gb
            for cls, prof in self._profiles.items()
            if cls not in self._multi_card
        )

    def _fallback_slot(self, current: CapacityPlan) -> GpuSlot:
        """未規劃模型的後備單一槽位：挑預算最寬鬆的卡（無 GPU 時回 CPU 後備）。"""
        if not current.gpu_ids:
            return GpuSlot(device_id=_CPU_FALLBACK_DEVICE_ID, slot_id=_DEFAULT_SLOT_ID)
        best = max(current.gpu_ids, key=lambda dev: current.budget_by_device.get(dev, 0.0))
        return GpuSlot(device_id=best, slot_id=_DEFAULT_SLOT_ID)

    # ── 預設規格 / 掃描（未注入時才用，含 lazy import） ────────────────────────

    @staticmethod
    def _default_model_specs() -> list[tuple[type, float, float, bool, int]]:
        """
        預設模型規格 ``(class, resident_gb, transient_gb, multi_card, max_slots_per_card)``，依 eager 優先序。

        - Qwen：``multi_card=True``、``max_slots=0``（= 用全域 QWEN_MAX_SLOTS_PER_GPU，同卡可塞多份）。
        - Saliency：``multi_card=True``、``max_slots=1``（每張放得下的卡剛好一份 → 真多卡分散、不過量）；
          排在 Qwen 之後（Qwen 仍優先佔卡）。
        - 其餘小模型：``multi_card=False``（單卡 best-fit，集中到 small_host）。
        lazy import 各 Manager，避免「import 本模組」就把 transformers/pyiqa/panns/onnxruntime 一併拉進來。
        """
        from model.qwen_model_manager import QwenModelManager
        from model.saliency_model_manager import SaliencyModelManager
        from model.whisper_model_manager import WhisperModelManager
        from model.laion_model_manager import LaionModelManager
        from model.musiq_model_manager import MusiqModelManager
        from model.audio_env_model_manager import AudioEnvModelManager

        return [
            (QwenModelManager, QWEN_RESIDENT_VRAM_GB, QWEN_TRANSIENT_VRAM_GB, True, 0),
            (SaliencyModelManager, SALIENCY_RESIDENT_VRAM_GB, SALIENCY_TRANSIENT_VRAM_GB, True, 1),
            (WhisperModelManager, WHISPER_RESIDENT_VRAM_GB, WHISPER_TRANSIENT_VRAM_GB, False, 0),
            (LaionModelManager, LAION_RESIDENT_VRAM_GB, LAION_TRANSIENT_VRAM_GB, False, 0),
            (MusiqModelManager, MUSIQ_RESIDENT_VRAM_GB, MUSIQ_TRANSIENT_VRAM_GB, False, 0),
            (AudioEnvModelManager, AUDIO_ENV_RESIDENT_VRAM_GB, AUDIO_ENV_TRANSIENT_VRAM_GB, False, 0),
        ]

    @staticmethod
    def _real_mem_scan(device_id: int) -> tuple[float, float]:
        """真實掃描：回傳指定卡的 ``(free_gb, total_gb)``。"""
        import torch
        free_b, total_b = torch.cuda.mem_get_info(device_id)
        return free_b / _BYTES_PER_GB, total_b / _BYTES_PER_GB

    @staticmethod
    def _detect_cuda_ids() -> list[int]:
        """極簡 CUDA 偵測（不 import pipeline 的 gpu_detect，維持 model 層獨立）。"""
        try:
            import torch
            if torch.cuda.is_available():
                return list(range(torch.cuda.device_count()))
        except ImportError:
            pass
        return []
