import torch
import librosa
import gc
from transformers import WhisperProcessor, WhisperForConditionalGeneration
from model.base_model_manager import BaseModelManager, synchronized_inference
from config.model_config import (
    AUDIO_ENV_MODEL_ID,
    AUDIO_ENV_MAX_NEW_TOKENS,
    AUDIO_ENV_NUM_BEAMS,
    AUDIO_SAMPLING_RATE,
)


class AudioEnvModelManager(BaseModelManager):
    """環境音效描述大腦 (whisper-tiny-audio-captioning)。"""

    def _initialize(self, device_id: int = 0):
        """初始化模型與處理器，並設定硬體加速與半精度。"""
        self.device = self.get_device_str(device_id)

        self.processor = WhisperProcessor.from_pretrained(AUDIO_ENV_MODEL_ID)

        # 強制使用 FP16 精度，以利與 Qwen3-VL 共存於 VRAM
        self.model = WhisperForConditionalGeneration.from_pretrained(
            AUDIO_ENV_MODEL_ID,
            torch_dtype=torch.float16 if self.device != "cpu" else torch.float32
        ).to(self.device)

        self.model.eval()

    @synchronized_inference
    def get_audio_description(self, audio_path: str) -> str:
        """輸入音檔路徑，回傳自然語言的環境描述。"""
        try:
            audio_array, sampling_rate = librosa.load(audio_path, sr=AUDIO_SAMPLING_RATE)

            inputs = self.processor(
                audio_array,
                sampling_rate=sampling_rate,
                return_tensors="pt"
            ).to(self.device)

            # 確保輸入特徵也是半精度
            if self.device != "cpu":
                inputs = {k: v.to(torch.float16) if v.is_floating_point() else v for k, v in inputs.items()}

            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=AUDIO_ENV_MAX_NEW_TOKENS,
                    num_beams=AUDIO_ENV_NUM_BEAMS,
                    early_stopping=True
                )
                caption = self.processor.batch_decode(output_ids, skip_special_tokens=True)[0]

            return caption.strip()

        except Exception as e:
            print(f"[AudioEnv Error] 環境音描述生成失敗: {e}")
            return "Ambient background noise"
        finally:
            # 強制回收 VRAM，避免批次處理時堆積過多顯存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def classify_environment(self, audio_path: str) -> list:
        """
        相容性介面：為了不破壞現有 VideoProcessor 的 Metadata 串接邏輯。
        回傳格式與原 CLAP 保持一致，但標籤改為真實環境描述。
        """
        description = self.get_audio_description(audio_path)
        return [{"sound": "environment_description", "caption": description, "score": 1.0}]
