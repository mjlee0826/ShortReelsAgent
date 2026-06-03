"""
StartupReporter：把「GpuCapacityManager 放置結果 + ExecutorRegistry 並行度」彙整成一張
啟動佈局表 (Reporter / Builder Pattern)。

讓使用者 warm up 完一眼看出：
- 每張 GPU 的 total / plan 時 free / BudgetGate 預算；
- 每個模型鋪在哪些 (device, slot)、單份常駐多大、eager 預載或 lazy 按需；
- 四個 Worker Pool（IO / CPU / GPU / API）各能同時跑幾條 thread，以及 asset driver 並行度。

純讀取 + 字串格式化，不改任何狀態；無 CUDA 時自動降級顯示。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from media_processor.pipeline.stage import ResourceType

if TYPE_CHECKING:
    from media_processor.pipeline.executor.executor_registry import ExecutorRegistry
    from model.gpu_capacity_manager import GpuCapacityManager

# 分隔線與欄寬具名常數（避免格式 magic number；CLAUDE.md）
_RULE_WIDTH = 70
_HEAVY_RULE = "═" * _RULE_WIDTH
_W_DEVICE = 10
_W_NUM = 13
_W_MODEL = 24
_W_RESIDENT = 14
_W_STATUS = 8
_W_POOL = 16
_W_THREADS = 9
# Pool 顯示順序（對應 ExecutorRegistry 四池）
_POOL_ORDER = (ResourceType.IO, ResourceType.CPU, ResourceType.GPU, ResourceType.API)


class StartupReporter:
    """彙整容量規劃與資源池並行度，:meth:`render` 產生多段對齊的啟動佈局表。"""

    def __init__(
        self,
        capacity_manager: "GpuCapacityManager",
        executor_registry: "ExecutorRegistry",
        max_assets_parallel: int,
    ):
        """綁定三個資料來源（容量規劃器 / 資源池註冊表 / asset 並行度上限）。"""
        self._capacity = capacity_manager
        self._executor_registry = executor_registry
        self._max_assets_parallel = max_assets_parallel

    def render(self) -> str:
        """組出三段表格（GPU VRAM / 模型放置 / Pool 並行度）成單一字串。"""
        sections = [
            _HEAVY_RULE,
            "Pipeline 啟動佈局 (Startup Layout)",
            _HEAVY_RULE,
            *self._gpu_section(),
            "",
            *self._model_section(),
            "",
            *self._pool_section(),
            _HEAVY_RULE,
        ]
        return "\n".join(sections)

    def _gpu_section(self) -> list[str]:
        """每卡 VRAM：total / plan 時 free / BudgetGate 預算。"""
        rows = self._capacity.device_rows()
        if not rows:
            return ["[GPU VRAM] （無 CUDA：模型走 CPU / lazy，BudgetGate 不啟用）"]
        out = [
            "[GPU VRAM]",
            f"  {'device':<{_W_DEVICE}}{'total(GB)':>{_W_NUM}}"
            f"{'free@plan':>{_W_NUM}}{'budget(GB)':>{_W_NUM}}",
        ]
        for dev, total, free, budget in rows:
            out.append(
                f"  {'cuda:' + str(dev):<{_W_DEVICE}}{total:>{_W_NUM}.1f}"
                f"{free:>{_W_NUM}.1f}{budget:>{_W_NUM}.1f}"
            )
        return out

    def _model_section(self) -> list[str]:
        """模型放置：單份常駐 / eager|lazy / placement（同卡多 slot 以 ×N 表示，放最後免被長字串擠歪）。"""
        out = [
            "[模型載入 / 放置]",
            f"  {'model':<{_W_MODEL}}{'resident(GB)':<{_W_RESIDENT}}"
            f"{'status':<{_W_STATUS}}placement",
        ]
        for name, slot_strs, resident, status in self._capacity.placement_rows():
            count = len(slot_strs)
            if count > 1:
                resident_str = f"{resident:.1f}×{count}"
            elif count == 1:
                resident_str = f"{resident:.1f}"
            else:
                resident_str = "-"
            out.append(
                f"  {name:<{_W_MODEL}}{resident_str:<{_W_RESIDENT}}"
                f"{status:<{_W_STATUS}}{self._compact_placement(slot_strs)}"
            )
        return out

    def _pool_section(self) -> list[str]:
        """四個 Worker Pool 的 max_workers + asset driver 並行度。"""
        out = [
            "[Worker Pool 並行度（同時可跑的 thread 數）]",
            f"  {'pool':<{_W_POOL}}{'threads':>{_W_THREADS}}",
        ]
        for resource_type in _POOL_ORDER:
            workers = self._executor_registry.get(resource_type).max_workers
            out.append(f"  {resource_type.value:<{_W_POOL}}{workers:>{_W_THREADS}}")
        out.append(
            f"  {'asset-driver':<{_W_POOL}}{self._max_assets_parallel:>{_W_THREADS}}"
            "   (MAX_ASSETS_PARALLEL)"
        )
        return out

    @staticmethod
    def _compact_placement(slot_strs: list[str]) -> str:
        """把 ['cuda:0#0','cuda:0#1'] 壓成 'cuda:0×2'；跨卡則逗號分隔（多卡 Qwen 一目了然）。"""
        if not slot_strs:
            return "-"
        counts: dict[str, int] = {}
        for slot in slot_strs:
            device = slot.split("#")[0]  # 取 'cuda:N'
            counts[device] = counts.get(device, 0) + 1
        return ",".join(f"{dev}×{n}" if n > 1 else dev for dev, n in counts.items())
