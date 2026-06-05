"""
BaseModelManager：執行緒安全的多 GPU Singleton 基底類別。

設計模式
--------
- **Template Method**：子類別只需實作 ``_initialize(device_id)``。
- **Registry**：以 ``(device_id, slot_id)`` tuple 為 key，每個槽位保有獨立實例，
  支援同卡多 instance Pool。
- **Double-Checked Locking**：建立實例時避免 race condition。
- **Strategy**：L2 ``GpuGate`` 為可替換策略，預設 ``BinaryGate``，
  GPU Capacity Manager 透過 :meth:`BaseModelManager.register_gate_factory`
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
import gc
import json
import time
import threading
import functools
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Callable, Iterator

from config.media_processor_config import OOM_RETRY_MAX_ATTEMPTS, OOM_RETRY_BACKOFF_SEC
from model.gpu_gate import GpuGate, BinaryGate, NO_PRIORITY
from model.resource_wait_clock import ResourceWaitClock


# 預設槽位 id：呼叫端未指定時用此值，向後相容既有「一卡一 instance」配置
_DEFAULT_SLOT_ID = 0


def _default_gate_factory(device_id: int) -> GpuGate:
    """
    預設 Gate 工廠：每張 GPU 一個 ``BinaryGate``。

    簽名收 ``device_id`` 以對齊 ``BudgetGate`` 需要的 per-device 預算
    （``BinaryGate`` 不需要 device_id，單純忽略），讓 :meth:`register_gate_factory`
    的工廠簽名統一為 ``Callable[[int], GpuGate]``。
    """
    return BinaryGate()


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


def is_cuda_oom(exc: Exception) -> bool:
    """
    判斷例外是否為 CUDA 顯存不足 (OOM 重試用)。

    同時涵蓋 ``torch.cuda.OutOfMemoryError`` 與部分版本只丟「訊息含 out of memory」的
    ``RuntimeError``，讓 OOM 重試不漏接;非 OOM 例外回 False 由呼叫端原樣處理。
    """
    try:
        import torch
        oom_cls = getattr(torch.cuda, "OutOfMemoryError", None)
        if oom_cls is not None and isinstance(exc, oom_cls):
            return True
    except ImportError:
        # 理論上不會發生於本專案;無 torch 即無 CUDA OOM
        pass
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


def oom_resilient(method):
    """
    裝飾器：推論方法遇 CUDA OOM 時釋放 VRAM + backoff 後重試，耗盡仍 OOM 才往上拋。

    **必須套在 ``@synchronized_inference`` 外層**（寫在其上方），使每次重試都在鎖外
    先釋放 VRAM、再重新取得 L2 GpuGate / L3 model lock，讓同卡其他 forward 或鄰居 process
    有機會把 VRAM 排空（優先「等待 / 重試」而非「卸載重載」以避免 thrash）。

    耗盡 ``OOM_RETRY_MAX_ATTEMPTS`` 次後 re-raise（由 Pipeline 隔離成 asset error），
    刻意**不**靜默吞成 null object —— OOM 失敗的 asset 應顯式標記 error。
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        last_oom: Exception | None = None
        for attempt in range(1, OOM_RETRY_MAX_ATTEMPTS + 1):
            try:
                return method(self, *args, **kwargs)
            except Exception as exc:
                if not is_cuda_oom(exc):
                    # 非 OOM 不在本裝飾器職責內，原樣往上拋（仍由方法內既有 except 決定 null object）
                    raise
                last_oom = exc
                # 鎖此刻已隨例外往外釋放，於鎖外釋放 VRAM 讓他人騰出空間
                BaseModelManager._release_gpu_memory()
                if attempt < OOM_RETRY_MAX_ATTEMPTS:
                    print(
                        f"[OOM Retry] {type(self).__name__} 第 {attempt}/{OOM_RETRY_MAX_ATTEMPTS} "
                        f"次遇 CUDA OOM，釋放 VRAM 後重試：{exc}"
                    )
                    # 線性 backoff：給同卡其他 forward / 鄰居 process 時間釋放 VRAM
                    time.sleep(OOM_RETRY_BACKOFF_SEC * attempt)
        print(
            f"[OOM Retry] {type(self).__name__} 連續 {OOM_RETRY_MAX_ATTEMPTS} 次 CUDA OOM，放棄重試"
        )
        raise last_oom
    return wrapper


class BaseModelManager(ABC):
    """執行緒安全、多 GPU、多槽位的 Singleton 基底。"""

    # ── L2 全域 GPU Gate Registry（class-level，跨 Manager 子類共用） ─────────
    # 同一 device_id 共用一個 Gate，跨 Manager 也共用，達成同卡互斥
    _GPU_GATES: dict[int, GpuGate] = {}
    # 建立新 Gate 時的互斥鎖（與 _instances 的建立鎖分開，避免不必要爭用）
    _GPU_GATES_LOCK = threading.Lock()
    # Gate 工廠：預設 per-device BinaryGate，由 Capacity Manager 換成 BudgetGate。
    # 簽名為 Callable[[int], GpuGate]（收 device_id），讓 BudgetGate 能依卡別給不同預算。
    _gate_factory: Callable[[int], GpuGate] = _default_gate_factory

    # 子類別可 override 提供 per-model「單次 forward 暫態峰值」VRAM 成本（單位 GB），
    # 預設 0（BinaryGate 忽略），BudgetGate 以此做預算記帳。
    # ⚠️ 應填 forward 暫態峰值（activation/KV cache/workspace），非常駐權重大小。
    INFERENCE_VRAM_COST_GB: float = 0.0

    # 子類別可 override 提供推論優先序（數值越大越優先）。Qwen 等主瓶頸設正值，
    # BudgetGate 會讓「有高優先在等」時低優先請求讓路，避免 Qwen 被小模型串流餓死。
    INFERENCE_PRIORITY: int = NO_PRIORITY

    def __init_subclass__(cls, **kwargs):
        """每個子類別擁有獨立的實例字典與建構鎖，避免不同 Manager 間互相干擾。"""
        super().__init_subclass__(**kwargs)
        # Key 為 (device_id, slot_id) tuple，支援同卡多 instance
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

    def warmup(self) -> None:
        """
        選用預熱 hook（Template Method）：啟動單執行緒階段，觸發「首次推論才會發生的 lazy import /
        原生擴充 dlopen」，預設不做事。

        為何需要：部分模型的解碼後端採延遲載入，第一次推論才 import .so（如 librosa→libsndfile、
        torchaudio→torchcodec）。若延後到執行期由多條 worker thread 同時首呼叫，會與其他執行緒正在
        進行的函式庫掃描（threadpoolctl 的 ``dl_iterate_phdr`` 持有動態連結器鎖 ``dl_load_write_lock``）
        形成「GIL ↔ 連結器鎖」鎖序倒置而**死結**（StallWatchdog C 層 dump 的根因之一）。
        啟動期單執行緒先各跑一次，這些原生擴充即提前 import 完成，執行期不再 dlopen，死結結構性消失。

        合約：**best-effort、不得拋例外**（預載失敗只記錄、不擋啟動，執行期仍會 lazy 再試）。
        只有「首呼叫才載原生擴充」的子類需要 override。
        """

    # ── L2 GPU Gate 管理（class method） ─────────────────────────────────────
    @classmethod
    def register_gate_factory(cls, factory: Callable[[int], GpuGate]) -> None:
        """
        替換全域 Gate 工廠，並清空既有 Gate 快取（升級 BudgetGate 用）。

        工廠簽名為 ``Callable[[int], GpuGate]``（收 ``device_id``），讓每張卡能拿到
        依自身 free VRAM 算出的不同預算。典型用法（GPU Capacity Manager 啟動時）::

            BaseModelManager.register_gate_factory(
                lambda device_id: BudgetGate(
                    total_gb=per_device_budget[device_id], safety_buffer_gb=1.5
                )
            )

        既有 Manager 子類完全不需修改即可享受新策略。
        """
        with cls._GPU_GATES_LOCK:
            cls._gate_factory = factory
            # 已建的 Gate 在新策略下無效，清空使下次 _get_gpu_gate 用新 factory 建立
            cls._GPU_GATES.clear()

    @classmethod
    def _get_gpu_gate(cls, device_id: int) -> GpuGate:
        """Double-checked locking 取得 device 對應 Gate，無則用 _gate_factory 依卡別建立。"""
        gate = cls._GPU_GATES.get(device_id)
        if gate is None:
            with cls._GPU_GATES_LOCK:
                gate = cls._GPU_GATES.get(device_id)
                if gate is None:
                    # 工廠收 device_id，BudgetGate 依該卡預算建立、BinaryGate 則忽略
                    gate = cls._gate_factory(device_id)
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

    @staticmethod
    def most_free_cuda_device() -> int:
        """
        回傳當下 free VRAM 最多的 CUDA device id（共用 GPU 上避開被鄰居佔住的卡）。

        給「不走 capacity pool、卻又要挑卡」的模型（如 Saliency 的 onnxruntime session）在載入時
        選最空的卡，避免硬撞滿載的 cuda:0。無 CUDA / 偵測異常一律回 0（``get_device_str`` 對應到 cpu）。
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return 0
            best_dev, best_free = 0, -1
            for dev in range(torch.cuda.device_count()):
                free_b, _total_b = torch.cuda.mem_get_info(dev)
                if free_b > best_free:
                    best_free, best_dev = free_b, dev
            return best_dev
        except Exception:
            # 任何偵測異常都不該擋住模型載入，退回 0
            return 0

    @staticmethod
    def _release_gpu_memory() -> None:
        """釋放 CUDA 快取 + 觸發 gc，供 :func:`oom_resilient` 在 OOM 重試前騰出 VRAM。"""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            # 無 torch 即無 CUDA 快取可釋放
            pass
        gc.collect()

    @contextmanager
    def _log_load(self, model_name: str) -> Iterator[None]:
        """
        記錄模型載入的起訖與耗時（Context Manager）。

        模型載入是整條流程中最耗時的一次性操作（可能含權重下載 / 量化），
        且每個 (device, slot) singleton 只發生一次，故值得印出供觀察；
        所有 Manager 共用同一入口，日後要改成正式 logging 只需改這一處。
        子類別 ``_initialize`` 把載入邏輯包進此 context manager 即可。
        """
        # device 屬性可能尚未設定（rembg / silero 由套件內部自行管理裝置）
        device = getattr(self, "device", None) or "內部管理"
        print(f"[{model_name}] 開始載入模型 (device={device})")
        start = time.perf_counter()
        yield
        # 載入失敗時例外會往上拋，不會印出「完成」，符合直覺
        print(f"[{model_name}] 模型載入完成，耗時 {time.perf_counter() - start:.1f}s")

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
            # GPU 路徑：依 device_id 取 Gate，預算成本與優先序由子類屬性提供
            # （BudgetGate 用成本記帳 + 優先序反餓死；BinaryGate 兩者皆忽略）
            with self._get_gpu_gate(self._device_id).acquire(
                self.INFERENCE_VRAM_COST_GB, self.INFERENCE_PRIORITY
            ):
                with self._acquire_inference_lock():
                    yield
        else:
            # CPU/API 路徑：只取 L3 model lock，不申請 L2
            with self._acquire_inference_lock():
                yield

    @contextmanager
    def _acquire_inference_lock(self) -> Iterator[None]:
        """
        取得 L3 model inference lock，且**只把「阻塞等鎖」計入 ResourceWaitClock**（持鎖運算仍算 compute）。

        走 pool 的模型每個 instance 同時只有一個借用者，L3 幾乎不爭用 → 計入趨近 0；但**單例共用**模型
        （VAD，或關掉合批時的 MUSIQ/LAION/Whisper/AudioEnv）由多條 asset thread 搶同一把 L3 鎖時，
        「等前一個 asset 用完」這段才會被正確歸為 wait 而非 compute——這正是 VAD 不走 pool、卻仍有
        序列化等待的歸因缺口。只量 ``acquire()``（阻塞段）；``yield`` 期間（真正推論）屬 compute，
        故與 compute 不重疊、也不與 L2 Gate 的等待量重複（Gate 的 measure 早在其 acquire 內結束）。
        """
        # 只測「等鎖」這段；拿到鎖後的 yield（實際推論）不納入等待
        with ResourceWaitClock.measure():
            self._inference_lock.acquire()
        try:
            yield
        finally:
            # finally 確保異常路徑也釋鎖，避免單例模型被一個失敗的推論永久卡住
            self._inference_lock.release()

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
