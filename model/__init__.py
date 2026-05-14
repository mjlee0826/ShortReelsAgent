"""
model 套件公開 API。

輕量介面（無重型依賴，可直接 import）：
    from model import BaseModelManager, ModelPool

重型 Manager（含 torch/transformers，維持延遲載入）：
    from model.qwen_model_manager import QwenModelManager
    from model.whisper_model_manager import WhisperModelManager
    # ... 其餘同理
"""
from model.base_model_manager import BaseModelManager
from model.model_pool import ModelPool

__all__ = ["BaseModelManager", "ModelPool"]
