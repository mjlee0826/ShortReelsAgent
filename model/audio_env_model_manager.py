"""環境音分類引擎，使用 PANNs CNN6 對 AudioSet 527 類進行推論。"""

import torch
import librosa
import numpy as np
import gc
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import AUDIO_ENV_TOP_K, AUDIO_SAMPLING_RATE, AUDIO_ENV_MIN_SCORE


class AudioEnvModelManager(BaseModelManager):
    """
    配接器模式 (Adapter Pattern)：封裝 PANNs CNN6 環境音分類器。
    PANNs（Pretrained Audio Neural Networks）以 AudioSet 527 類訓練，
    專為環境音設計，比 Whisper 架構更適合非語音聲音的分類任務。
    輸出 top-k 分類標籤與信心分數，結構化且易於下游 LLM 理解。
    """

    def _initialize(self, device_id: int = 0):
        """載入 PANNs CNN6 模型（panns_inference 套件）。"""
        from panns_inference import AudioTagging
        self.device = self.get_device_str(device_id)
        # AudioTagging 內部自動處理 GPU/CPU 分配
        self._tagger = AudioTagging(checkpoint_path=None, device=self.device)

    @synchronized_inference
    def classify_environment(self, audio_path: str) -> list:
        """
        對音訊檔執行環境音分類，回傳 top-k 標籤與信心分數列表。
        輸出格式：[{"label": "crowd_cheering", "score": 0.82}, ...]
        失敗時靜默回傳空列表，不阻斷主流程。
        """
        try:
            audio_array, _ = librosa.load(audio_path, sr=AUDIO_SAMPLING_RATE, mono=True)
            # PANNs 期望輸入形狀為 (batch, samples)
            audio_tensor = audio_array[np.newaxis, :]

            with torch.no_grad():
                _, clipwise_output = self._tagger.inference(audio_tensor)

            # clipwise_output shape: (1, 527)
            scores = clipwise_output[0]
            top_indices = np.argsort(scores)[::-1][:AUDIO_ENV_TOP_K]

            labels = self._tagger.labels
            return [
                {"label": labels[idx], "score": round(float(scores[idx]), 4)}
                for idx in top_indices
                if scores[idx] > AUDIO_ENV_MIN_SCORE
            ]

        except Exception as e:
            print(f"[AudioEnv Error] 環境音分類失敗: {e}")
            return []
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
