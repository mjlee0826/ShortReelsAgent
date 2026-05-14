"""
BaseModelManager：執行緒安全的多 GPU Singleton 基底類別。

設計模式：
  - Template Method：子類別只需實作 _initialize(device_id)
  - Registry：以 device_id 為 key，每張 GPU 保有獨立實例
  - Double-Checked Locking：建立實例時避免 race condition
  - synchronized_inference 裝飾器：確保同一實例的推論方法同一時刻只被一個執行緒執行

多 GPU 用法：
    manager_gpu0 = QwenModelManager()            # 預設 device_id=0
    manager_gpu1 = QwenModelManager(device_id=1) # GPU 1 的獨立實例

多執行緒 + 多 GPU 並行推論請搭配 model.ModelPool。
同一實例在多執行緒下會序列化排隊（由 @synchronized_inference 保證）。
"""
import re
import json
import threading
import functools
from abc import ABC, abstractmethod
from contextlib import contextmanager


def synchronized_inference(method):
    """
    裝飾器：對同一 model 實例的推論方法加入互斥鎖。

    - 同一實例：多執行緒請求依序排隊，防止 empty_cache() 競爭與 VRAM OOM。
    - 不同實例（不同 GPU）：完全並行，鎖彼此獨立。
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._inference_lock:
            return method(self, *args, **kwargs)
    return wrapper


class BaseModelManager(ABC):
    """執行緒安全、多 GPU 的 Singleton 基底。"""

    def __init_subclass__(cls, **kwargs):
        """每個子類別擁有獨立的實例字典與建構鎖，避免不同 Manager 間互相干擾。"""
        super().__init_subclass__(**kwargs)
        cls._instances: dict[int, 'BaseModelManager'] = {}
        cls._creation_lock = threading.Lock()

    def __new__(cls, device_id: int = 0):
        # Fast path：實例已存在，直接回傳（無鎖，高併發下效能佳）
        if device_id in cls._instances:
            return cls._instances[device_id]

        # Slow path：加鎖後再次確認，防止多執行緒同時通過 fast path
        with cls._creation_lock:
            if device_id not in cls._instances:
                instance = object.__new__(cls)
                instance._device_id = device_id
                # 每個實例有自己的推論鎖，不同 GPU 的實例鎖彼此獨立
                instance._inference_lock = threading.Lock()
                instance._initialize(device_id)
                cls._instances[device_id] = instance

        return cls._instances[device_id]

    def __init__(self, device_id: int = 0):
        """空實作，防止 object.__init__ 因多餘參數而拋出 TypeError。"""

    @abstractmethod
    def _initialize(self, device_id: int = 0):
        """子類別必須實作：完成模型載入並將結果存為 self 屬性。"""

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
