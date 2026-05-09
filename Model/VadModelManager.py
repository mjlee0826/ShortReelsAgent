import torch
from Model.BaseModelManager import BaseModelManager

class VadModelManager(BaseModelManager):
    """語音活動偵測大腦 (Silero VAD)，阻斷 Whisper 靜音幻覺。"""

    def _initialize(self):
        # 透過 Torch Hub 載入 Silero VAD (免安裝額外套件，自動下載)
        self.model, utils = torch.hub.load(
            repo_or_dir='snakers4/silero-vad', 
            model='silero_vad', 
            force_reload=False
        )
        # 解構官方提供的輔助函式
        self.get_speech_timestamps, _, self.read_audio, _, _ = utils

    def has_speech(self, audio_path: str) -> bool:
        """
        判斷音檔是否包含人聲。
        """
        try:
            wav = self.read_audio(audio_path, sampling_rate=16000)
            # 取得人聲發生的時間戳記片段
            speech_timestamps = self.get_speech_timestamps(wav, self.model, sampling_rate=16000)
            # 如果陣列有長度，代表有人講話
            return len(speech_timestamps) > 0
        except Exception as e:
            print(f"[VAD Error] 語音偵測失敗: {e}")
            # 保守策略：若偵測失敗，預設為有講話，交由 Whisper 處理
            return True