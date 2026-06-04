"""
SystemHealthProbe：機器資源健康探針 (best-effort 觀測；Probe + Value Object Pattern)。

動機
----
某些「卡住 / 超慢」其實是**機器當下被外部塞爆**——CPU 被別人佔滿、RAM 不足在 swap、共用 GPU
被鄰居吃光 VRAM——而不是 pipeline 本身的 bug。把這些系統指標跟 ``StallWatchdog`` 的心跳印在
**同一份 log**，就能直接看出「是程式卡住，還是機器很糟」，免去事後再去翻 ``top`` / ``vmstat``。

設計
----
- ``psutil`` / ``torch`` 皆 **best-effort**：缺套件或讀取失敗一律降級略過，絕不影響主流程。
- swap 看「自上次取樣的差分速率」而非累積量——持續 swap-in/out 才是壞徵兆（累積量含開機以來歷史），
  故 :class:`SystemHealthProbe` 保存上次取樣狀態以算速率。
- ``snapshot()`` 回不可變 :class:`SystemHealthSnapshot`（Value Object）；``render()`` 轉成單行字串，
  各指標超過具名門檻即標 ``⚠``，讓壞掉的那項一眼跳出來。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

# ── 健康門檻常數（避免 magic number；超過即標 ⚠）─────────────────────────────────
# 1 分鐘 load average / 邏輯核心數 ≥ 此值 → CPU 被超額認購（自家 + 鄰居）
_LOAD_WARN_RATIO = 1.0
# 已用實體記憶體百分比 ≥ 此值 → RAM 吃緊，逼近 swap
_RAM_WARN_PERCENT = 90.0
# swap in 或 out 速率 ≥ 此值（MB/s）→ 正在 swap thrash（解碼 / CPU stage 慢 10–100× 的元兇）
_SWAP_RATE_WARN_MB_S = 1.0
# 單卡 free VRAM ≤ 此值（GB）→ 該卡幾乎被佔滿（鄰居 process 或自家放置過滿）
_GPU_FREE_WARN_GB = 2.0

# 單位換算
_BYTES_PER_GB = 1024 ** 3
_BYTES_PER_MB = 1024 ** 2


@dataclass(frozen=True)
class _GpuMem:
    """單卡 VRAM 快照（Value Object）。"""

    device_id: int
    free_gb: float
    total_gb: float


@dataclass(frozen=True)
class SystemHealthSnapshot:
    """一次系統健康取樣結果（不可變 Value Object）；欄位取不到時為 ``None``。"""

    load1: Optional[float]
    cpu_count: int
    ram_used_gb: Optional[float]
    ram_total_gb: Optional[float]
    ram_percent: Optional[float]
    swap_used_gb: Optional[float]
    swap_in_mb_s: Optional[float]
    swap_out_mb_s: Optional[float]
    gpus: list[_GpuMem] = field(default_factory=list)


class SystemHealthProbe:
    """取樣 CPU load / RAM / swap 速率 / 各 GPU free VRAM，並渲染成單行健康報告。"""

    def __init__(self) -> None:
        """初始化 swap 速率所需的上次取樣狀態（首次取樣速率視為 0）。"""
        # 上次取樣的 swap 累積 (sin, sout) bytes 與時刻，用來算差分速率
        self._prev_swap: Optional[tuple[int, int]] = None
        self._prev_ts: Optional[float] = None

    # ── 取樣 ─────────────────────────────────────────────────────────────────
    def snapshot(self) -> SystemHealthSnapshot:
        """取一份系統健康快照（每項 best-effort，失敗該項給 ``None``）。"""
        load1 = self._read_load1()
        cpu_count = os.cpu_count() or 0
        ram_used_gb, ram_total_gb, ram_percent = self._read_ram()
        swap_used_gb, swap_in_mb_s, swap_out_mb_s = self._read_swap()
        gpus = self._read_gpus()
        return SystemHealthSnapshot(
            load1=load1,
            cpu_count=cpu_count,
            ram_used_gb=ram_used_gb,
            ram_total_gb=ram_total_gb,
            ram_percent=ram_percent,
            swap_used_gb=swap_used_gb,
            swap_in_mb_s=swap_in_mb_s,
            swap_out_mb_s=swap_out_mb_s,
            gpus=gpus,
        )

    def render(self) -> str:
        """把一次快照渲染成單行 ``[SysHealth] ...`` 字串；完全取不到資料時回空字串。"""
        s = self.snapshot()
        parts: list[str] = []

        # CPU load：load / 核心數 ≥ 門檻標 ⚠（自家 176 thread + 鄰居都會反映在這）
        if s.load1 is not None and s.cpu_count:
            warn = "⚠" if s.load1 >= s.cpu_count * _LOAD_WARN_RATIO else ""
            parts.append(f"load={s.load1:.1f}/{s.cpu_count}{warn}")

        # RAM：用量 / 總量 + 百分比
        if s.ram_used_gb is not None and s.ram_total_gb is not None:
            warn = "⚠" if (s.ram_percent or 0) >= _RAM_WARN_PERCENT else ""
            parts.append(
                f"RAM={s.ram_used_gb:.0f}/{s.ram_total_gb:.0f}GB({s.ram_percent:.0f}%{warn})"
            )

        # swap：用量 + in/out 速率（正在 swap 才是壞徵兆 → 看速率）
        if s.swap_used_gb is not None:
            rate_warn = ""
            rate_str = ""
            if s.swap_in_mb_s is not None and s.swap_out_mb_s is not None:
                if max(s.swap_in_mb_s, s.swap_out_mb_s) >= _SWAP_RATE_WARN_MB_S:
                    rate_warn = "⚠"
                rate_str = f" in={s.swap_in_mb_s:.0f} out={s.swap_out_mb_s:.0f}MB/s{rate_warn}"
            parts.append(f"swap={s.swap_used_gb:.1f}GB{rate_str}")

        # 各 GPU free VRAM：低於門檻標 ⚠（共用機鄰居佔走 / 自家放置過滿）
        if s.gpus:
            gpu_strs = []
            for g in s.gpus:
                warn = "⚠" if g.free_gb <= _GPU_FREE_WARN_GB else ""
                gpu_strs.append(f"{g.device_id}={g.free_gb:.1f}{warn}")
            parts.append("GPUfree(GB): " + " ".join(gpu_strs))

        return "[SysHealth] " + "  ".join(parts) if parts else ""

    # ── 各指標讀取（best-effort，全程吞例外） ──────────────────────────────────
    @staticmethod
    def _read_load1() -> Optional[float]:
        """讀 1 分鐘 load average（非 Unix / 取不到回 None）。"""
        try:
            return os.getloadavg()[0]
        except (OSError, AttributeError):
            return None

    @staticmethod
    def _read_ram() -> tuple[Optional[float], Optional[float], Optional[float]]:
        """讀 (已用 GB, 總量 GB, 已用百分比)；psutil 缺失回三個 None。"""
        try:
            import psutil
            vm = psutil.virtual_memory()
            return (
                (vm.total - vm.available) / _BYTES_PER_GB,
                vm.total / _BYTES_PER_GB,
                vm.percent,
            )
        except Exception:
            return None, None, None

    def _read_swap(self) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """讀 (swap 已用 GB, swap-in MB/s, swap-out MB/s)；速率由與上次取樣的差分算出。"""
        try:
            import psutil
            sw = psutil.swap_memory()
            now = time.monotonic()
            in_rate = out_rate = None
            if self._prev_swap is not None and self._prev_ts is not None:
                elapsed = now - self._prev_ts
                if elapsed > 0:
                    # sin/sout 為開機以來累積 bytes，差分 / 時間 = 當前速率（只有持續 swap 才會非 0）
                    in_rate = (sw.sin - self._prev_swap[0]) / elapsed / _BYTES_PER_MB
                    out_rate = (sw.sout - self._prev_swap[1]) / elapsed / _BYTES_PER_MB
            self._prev_swap = (sw.sin, sw.sout)
            self._prev_ts = now
            return sw.used / _BYTES_PER_GB, in_rate, out_rate
        except Exception:
            return None, None, None

    @staticmethod
    def _read_gpus() -> list[_GpuMem]:
        """讀各 CUDA 卡的 (free, total) VRAM；無 torch / 無 CUDA 回空列表。"""
        try:
            import torch
            if not torch.cuda.is_available():
                return []
            rows: list[_GpuMem] = []
            for dev in range(torch.cuda.device_count()):
                free_b, total_b = torch.cuda.mem_get_info(dev)
                rows.append(_GpuMem(dev, free_b / _BYTES_PER_GB, total_b / _BYTES_PER_GB))
            return rows
        except Exception:
            return []
