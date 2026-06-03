"""
VadModelManager：語音活動偵測（VAD）管理器，使用 Silero VAD 判斷音檔是否包含人聲。

設計模式
--------
- **Template Method**：繼承 ``BaseModelManager``，只實作 ``_initialize`` 與業務方法，
  鎖序與 Singleton 由基底類別提供。
- **保守策略（Conservative Null Object）**：偵測失敗時預設回傳 ``True``（假設有語音），
  避免靜音誤判讓 Whisper 白跑；若誤判方向可接受，比「靜默丟棄」更安全。

GPU 策略
--------
Silero VAD 極輕量（毫秒級 CPU 推論），顯式設 ``self.device = "cpu"``，
L2 BudgetGate 依 ``_uses_gpu`` 自動跳過，不佔任何 GPU 預算。
"""
import torch
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import VAD_REPO, VAD_SAMPLING_RATE


class VadModelManager(BaseModelManager):
    """語音活動偵測大腦 (Silero VAD)，阻斷 Whisper 靜音幻覺。"""

    def _initialize(self, device_id: int = 0):
        """
        透過 Torch Hub 載入 Silero VAD，免安裝額外套件。

        Silero VAD 極輕量、本就在 CPU 跑（ms 級），顯式標記 ``self.device='cpu'`` 讓 L2 BudgetGate
        依 ``_uses_gpu`` 自動跳過 —— 它不該佔 GPU 預算，也不該成為共用卡上的 VRAM 變數。
        """
        with self._log_load("VAD"):
            self.device = "cpu"
            self.model, utils = torch.hub.load(
                repo_or_dir=VAD_REPO,
                model='silero_vad',
                force_reload=False
            )
            # 解構官方提供的輔助函式
            self.get_speech_timestamps, _, self.read_audio, _, _ = utils

    @synchronized_inference
    def has_speech(self, audio_path: str) -> bool:
        """
        判斷音檔是否包含人聲。

        偵測失敗時採保守策略：回傳 ``True`` 讓 Whisper 有機會處理，
        避免靜音誤判造成有效語音被靜默丟棄。
        """
        try:
            wav = self.read_audio(audio_path, sampling_rate=VAD_SAMPLING_RATE)
            speech_timestamps = self.get_speech_timestamps(wav, self.model, sampling_rate=VAD_SAMPLING_RATE)
            return len(speech_timestamps) > 0
        except Exception as e:
            print(f"[VAD Error] 語音偵測失敗: {e}")
            # 保守策略：若偵測失敗，預設為有講話，交由 Whisper 處理
            return True
