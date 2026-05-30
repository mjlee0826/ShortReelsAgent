"""
BaseModelManager：執行緒安全的多 GPU Singleton 基底類別。

設計模式
--------
- **Template Method**：子類別只需實作 ``_initialize(device_id)``。
- **Registry**：以 ``(device_id, slot_id)`` 為 key，每個槽位保有獨立實例。
  Week 1 起 key 從單一 ``device_id`` 升級為 tuple，預備 Week 3b 同卡多 instance Pool。
- **Double-Checked Locking**：建立實例時避免 race condition。
- **Strategy**：L2 ``GpuGate`` 為可替換策略，Week 1 預設 ``BinaryGate``，
  Week 3b GPU Capacity Manager 透過 :meth:`BaseModelManager.register_gate_factory`
  一行替換成 ``BudgetGate``，Manager 子類零改動。
- **synchronized_inference 裝飾器**：對推論方法零侵入地套用「L2 GPU gate → L3 model lock」鎖序。

鎖層級
------
鎖層級 L1 (ModelPool) → L2 (GpuGate) → L3 (model lock) 的詳細設計與不可省略的反例，
見 ``docs/lock_design.md``。

多 GPU 與多槽位用法
-------------------
::

    manager_gpu0         = QwenModelManager()                              # (0, 0) 預設
    manager_gpu1         = QwenModelManager(device_id=1)                   # (1, 0)
    manager_gpu0_slot1   = QwenModelManager(device_id=0, slot_id=1)        # (0, 1) 同卡第二份

同一槽位的多執行緒會序列化排隊（由 ``@synchronized_inference`` 透過 :meth:`inference_guard` 保證），
跨槽位 / 跨 device 則允許併發（受 L2 GpuGate 策略控制）。
"""
import re
import json
import threading
import functools
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Callable, Iterator

from model.gpu_gate import GpuGate, BinaryGate


# 預設槽位 id：呼叫端未指定時用此值，向後相容既有「一卡一 instance」配置
_DEFAULT_SLOT_ID = 0


def synchronized_inference(method):
    """
    裝飾器：對推論方法套用「L2 GPU gate → L3 model lock」鎖序。

    對推論方法零侵入：呼叫端與既有方法簽名完全不變，只是多了鎖序保護。
    內部委派給 :meth:`BaseModelManager.inference_guard`，
    讓 BatchCollector 與其他不繞此裝飾器的路徑也能共用同樣鎖序。
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        # 鎖序統一在 inference_guard 內，這裡單純委派以降低耦合
        with self.inference_guard():
            return method(self, *args, **kwargs)
    return wrapper


class BaseModelManager(ABC):
    """執行緒安全、多 GPU、多槽位的 Singleton 基底。"""

    # ── L2 全域 GPU Gate Registry（class-level，跨 Manager 子類共用） ─────────
    # 同一 device_id 共用一個 Gate，跨 Manager 也共用，達成同卡互斥
    _GPU_GATES: dict[int, GpuGate] = {}
    # 建立新 Gate 時的互斥鎖（與 _instances 的建立鎖分開，避免不必要爭用）
    _GPU_GATES_LOCK = threading.Lock()
    # Gate 工廠：Week 1 預設 BinaryGate，Week 3b 由 Capacity Manager 換 BudgetGate
    _gate_factory: Callable[[], GpuGate] = BinaryGate

    # 子類別可 override 提供 per-model VRAM 預算（單位 GB），
    # Week 1 預設 0（BinaryGate 忽略），Week 3b BudgetGate 才會使用
    INFERENCE_VRAM_COST_GB: float = 0.0

    def __init_subclass__(cls, **kwargs):
        """每個子類別擁有獨立的實例字典與建構鎖，避免不同 Manager 間互相干擾。"""
        super().__init_subclass__(**kwargs)
        # Key 為 (device_id, slot_id) tuple，支援同卡多 instance（Week 3b 紅利）
        cls._instances: dict[tuple[int, int], 'BaseModelManager'] = {}
        cls._creation_lock = threading.Lock()

    def __new__(cls, device_id: int = 0, slot_id: int = _DEFAULT_SLOT_ID):
        """
        以 (device_id, slot_id) 取得或建立 Singleton。

        Fast path 無鎖直查，slow path 加鎖再次確認，確保多執行緒下不重複建立。
        """
        key = (device_id, slot_id)
        # Fast path：實例已存在，直接回傳（無鎖，高併發下效能佳）
        if key in cls._instances:
            return cls._instances[key]

        # Slow path：加鎖後再次確認，防止多執行緒同時通過 fast path
        with cls._creation_lock:
            if key not in cls._instances:
                instance = object.__new__(cls)
                instance._device_id = device_id
                instance._slot_id = slot_id
                # 每個 instance 有自己的 L3 推論鎖，不同 instance 的鎖彼此獨立
                instance._inference_lock = threading.Lock()
                instance._initialize(device_id)
                cls._instances[key] = instance

        return cls._instances[key]

    def __init__(self, device_id: int = 0, slot_id: int = _DEFAULT_SLOT_ID):
        """空實作，防止 ``object.__init__`` 因多餘參數而拋出 ``TypeError``。"""

    @abstractmethod
    def _initialize(self, device_id: int = 0):
        """子類別必須實作：完成模型載入並將結果存為 self 屬性。"""

    # ── L2 GPU Gate 管理（class method） ─────────────────────────────────────
    @classmethod
    def register_gate_factory(cls, factory: Callable[[], GpuGate]) -> None:
        """
        替換全域 Gate 工廠，並清空既有 Gate 快取（Week 3b 升級 BudgetGate 用）。

        典型用法（Week 3b GPU Capacity Manager 啟動時呼叫一次）::

            BaseModelManager.register_gate_factory(
                lambda: BudgetGate(total_gb=24.0, safety_buffer_gb=1.5)
            )

        既有 Manager 子類完全不需修改即可享受新策略。
        """
        with cls._GPU_GATES_LOCK:
            cls._gate_factory = factory
            # 已建的 Gate 在新策略下無效，清空使下次 _get_gpu_gate 用新 factory 建立
            cls._GPU_GATES.clear()

    @classmethod
    def _get_gpu_gate(cls, device_id: int) -> GpuGate:
        """Double-checked locking 取得 device 對應 Gate，無則用 _gate_factory 建立。"""
        gate = cls._GPU_GATES.get(device_id)
        if gate is None:
            with cls._GPU_GATES_LOCK:
                gate = cls._GPU_GATES.get(device_id)
                if gate is None:
                    gate = cls._gate_factory()
                    cls._GPU_GATES[device_id] = gate
        return gate

    # ── 工具方法 ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_device_str(device_id: int) -> str:
        """根據 CUDA 可用性回傳裝置字串（例如 'cuda:1' 或 'cpu'）。"""
        try:
            import torch
            if torch.cuda.is_available():
                return f"cuda:{device_id}"
        except ImportError:
            pass
        return "cpu"

    def _uses_gpu(self) -> bool:
        """
        判斷此 instance 是否需要走 L2 GPU Gate。

        依 ``self.device`` 是否為 ``cuda*`` 字串自動切換；
        CPU 模型（rembg / silero）與雲端 API 模型（Gemini）一律跳過 L2。
        """
        device = getattr(self, "device", None)
        if device is None:
            return False
        return str(device).lower().startswith("cuda")

    @contextmanager
    def inference_guard(self) -> Iterator[None]:
        """
        鎖序：L2 GPU Gate → L3 model inference lock。

        所有推論路徑（裝飾器、BatchCollector）共用此入口，
        確保鎖序一致，結構上不可能形成循環等待。CPU/API 模型自動跳過 L2。
        """
        if self._uses_gpu():
            # GPU 路徑：依 device_id 取 Gate，預算成本由子類 INFERENCE_VRAM_COST_GB 提供
            with self._get_gpu_gate(self._device_id).acquire(self.INFERENCE_VRAM_COST_GB):
                with self._inference_lock:
                    yield
        else:
            # CPU/API 路徑：只取 L3 model lock，不申請 L2
            with self._inference_lock:
                yield

    def _parse_json_output(self, text: str) -> dict:
        """
        共用強健 JSON 解析器：
        自動移除 Markdown 程式碼圍欄，再萃取第一個完整的 JSON 物件。
        """
        try:
            cleaned = text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[-1].split("```")[0].strip()
            elif "```" in cleaned:
                parts = cleaned.split("```")
                cleaned = parts[1].strip() if len(parts) > 1 else cleaned

            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))

            return {"caption": cleaned}
        except Exception as e:
            print(f"[JSON Parse Error] 解析失敗: {e}")
            return {"caption": "Unknown action"}
