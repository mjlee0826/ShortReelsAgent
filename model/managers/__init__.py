"""
model.managers 套件:具體模型管理器(各自包裝一個 ML 模型)。

Qwen / Whisper / Gemini / LAION / MUSIQ / Saliency / VAD / AudioEnv / MediaPipe。

刻意不在此 ``__init__`` 做 eager re-export:每個 manager 都會牽動 torch/transformers 等
重型依賴,集中 import 會破壞「用到才載入」的延遲載入(降 VRAM)。呼叫端一律以子模組路徑
import,例如 ``from model.managers.qwen_model_manager import QwenModelManager``。
"""
