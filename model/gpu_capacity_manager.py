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
from dataclasses import dataclass
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
        mem_scan: Optional[Callable[[int], tuple[float, float]]] = None,
    ):
        """
        準備規劃所需的裝置清單、模型規格與掃描函式（規劃延遲到首次 :meth:`plan`）。

        Args:
            gpu_ids: 明示裝置清單（主要供測試 / 呼叫端傳入）；``None`` 時自動偵測 CUDA。
            profiles / multi_card_models / eager_order: 模型規格；任一為 ``None`` 時才 lazy 組預設值
                （預設值需 import 各 Manager 類別，故注入完整三者即可完全避開重依賴）。
            safety_buffer_gb: 每卡預留給系統 / 鄰居的 VRAM。
            max_slots_per_gpu: 多卡模型（Qwen）同卡 instance 份數上限；``0``（預設）= 依該卡 free VRAM
                自動算「可真正並行的份數」，``>0`` = 取 min(本值, 自動值) 當上限。對應 config ``QWEN_MAX_SLOTS_PER_GPU``。
            mem_scan: ``device_id → (free_gb, total_gb)`` 掃描函式；``None`` 時用真 ``mem_get_info``。
        """
        self._gpu_ids = list(gpu_ids) if gpu_ids is not None else self._detect_cuda_ids()
        # 任一規格缺失才 lazy 組預設（避免測試注入時仍 import 重依賴）
        if profiles is None or multi_card_models is None or eager_order is None:
            specs = self._default_model_specs()
            default_profiles = {c: ModelVramProfile(r, t) for c, r, t, _m in specs}
            default_order = [c for c, _r, _t, _m in specs]
            default_multi = {c for c, _r, _t, m in specs if m}
        self._profiles = profiles if profiles is not None else default_profiles
        self._eager_order = eager_order if eager_order is not None else default_order
        self._multi_card = multi_card_models if multi_card_models is not None else default_multi
        self._buffer = safety_buffer_gb
        self._max_slots_per_gpu = max_slots_per_gpu
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

    # ── 規劃核心 ─────────────────────────────────────────────────────────────

    def _compute_plan(self) -> CapacityPlan:
        """掃描 free VRAM → 依優先序 check-before-load 放置 → 算每卡剩餘預算。"""
        gpu_ids = self._gpu_ids
        if not gpu_ids:
            # 無 GPU：空計畫，所有模型視為 lazy（實際走 CPU 後備槽位）
            return CapacityPlan({}, {}, tuple(), frozenset(self._profiles), tuple())

        # remaining[dev] 為「扣掉已放置常駐權重後」的剩餘 free VRAM（GB）
        remaining = {dev: self._mem_scan(dev)[0] for dev in gpu_ids}
        slots_by_model: dict[type, list[GpuSlot]] = {}
        eager: list[type] = []
        lazy: set[type] = set()

        # 依 eager 優先序逐一放置：Qwen 在最前且多卡，先把它的常駐位置佔走
        for model in self._eager_order:
            profile = self._profiles[model]
            placed = self._place_model(model, profile, gpu_ids, remaining)
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
        )

    def _place_model(
        self,
        model: type,
        profile: ModelVramProfile,
        gpu_ids: list[int],
        remaining: dict[int, float],
    ) -> list[GpuSlot]:
        """
        為單一模型挑槽位並就地扣除 remaining（check-before-load）。

        - 多卡模型（Qwen）：每張「放得下 resident + buffer」的卡各放一份。
        - 單卡模型：挑剩餘最寬鬆且放得下的卡放單份。
        放不下回空列表（→ lazy）。``buffer`` 留作不被任何模型常駐佔用的頭空間。
        """
        need = profile.resident_gb + self._buffer
        if model in self._multi_card:
            # 多卡模型（Qwen）：每張卡依 free VRAM 算同卡份數（同卡多 slot ⇒ 同卡可並行多條 forward）
            placed = []
            for dev in gpu_ids:
                count = self._multi_card_slot_count(profile, remaining[dev])
                for slot_id in range(count):
                    placed.append(GpuSlot(device_id=dev, slot_id=slot_id))
                    # 每份各扣一份常駐權重；buffer 是保留頭空間，不從預算實扣
                    remaining[dev] -= profile.resident_gb
            return placed

        candidates = [dev for dev in gpu_ids if remaining[dev] >= need]
        if not candidates:
            return []
        best = max(candidates, key=lambda dev: remaining[dev])
        remaining[best] -= profile.resident_gb
        return [GpuSlot(device_id=best, slot_id=_DEFAULT_SLOT_ID)]

    def _multi_card_slot_count(self, profile: ModelVramProfile, free_on_dev: float) -> int:
        """
        算多卡模型（Qwen）在單張卡上要放幾份 instance（同卡多 slot）。

        每條「能真正並行的 lane」需 resident（常駐權重）+ transient（forward 暫態）才有意義：
        只塞得下額外 resident、塞不下其 transient 的 instance 只會在 L2 BudgetGate 空等，純浪費 VRAM；
        且 Qwen 多 slot 會與同卡小模型共存，故先預留所有單卡模型常駐，再算「放得下幾條完整 lane」，
        避免擠掉小模型常駐位 / 撐爆同卡併發暫態預算。

        自動份數 = ``floor((free − 單卡常駐總和 − buffer) / (resident + transient))``，
        只要常駐放得下就至少 1 份（單份 transient 不足由 ``BudgetGate`` 的 ``in_flight==0`` over-budget 兜底）。
        ``self._max_slots_per_gpu > 0`` 時作為「上限」再夾住自動值（取 min，不會超過可並行份數）；
        ``≤ 0``（預設）時純自動。
        """
        # 硬條件：連一份常駐（+buffer）都放不下 → 此卡不放（與單卡分支的 need 判準一致）
        if free_on_dev < profile.resident_gb + self._buffer:
            return 0
        # 預留其餘單卡模型常駐，避免 Qwen 多 slot 吃掉小模型常駐位 / 撐爆同卡併發暫態預算
        usable = free_on_dev - self._single_card_resident_total() - self._buffer
        per_lane = profile.resident_gb + profile.transient_gb  # 一條可並行 lane 的 VRAM 足跡
        useful = int(usable // per_lane) if per_lane > 0 else 1
        # 硬條件已過 → 至少 1 份（即使 usable 因小模型預留而不足一條完整 lane）
        useful = max(1, useful)
        # 手動上限（>0）再夾；≤0 為自動不夾
        if self._max_slots_per_gpu > 0:
            return min(self._max_slots_per_gpu, useful)
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
    def _default_model_specs() -> list[tuple[type, float, float, bool]]:
        """
        預設模型規格 ``(class, resident_gb, transient_gb, multi_card)``，依 eager 優先序排列。

        Qwen 第一且 ``multi_card=True``（鋪滿可放下的每張卡）；其餘小模型單卡、依重要性排序。
        lazy import 各 Manager 類別，避免「import 本模組」就把 transformers/pyiqa/panns 一併拉進來。
        """
        from model.qwen_model_manager import QwenModelManager
        from model.whisper_model_manager import WhisperModelManager
        from model.laion_model_manager import LaionModelManager
        from model.musiq_model_manager import MusiqModelManager
        from model.audio_env_model_manager import AudioEnvModelManager

        return [
            (QwenModelManager, QWEN_RESIDENT_VRAM_GB, QWEN_TRANSIENT_VRAM_GB, True),
            (WhisperModelManager, WHISPER_RESIDENT_VRAM_GB, WHISPER_TRANSIENT_VRAM_GB, False),
            (LaionModelManager, LAION_RESIDENT_VRAM_GB, LAION_TRANSIENT_VRAM_GB, False),
            (MusiqModelManager, MUSIQ_RESIDENT_VRAM_GB, MUSIQ_TRANSIENT_VRAM_GB, False),
            (AudioEnvModelManager, AUDIO_ENV_RESIDENT_VRAM_GB, AUDIO_ENV_TRANSIENT_VRAM_GB, False),
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
