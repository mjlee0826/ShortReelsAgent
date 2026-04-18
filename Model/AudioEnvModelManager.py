import torch
import librosa
import gc
from transformers import WhisperProcessor, WhisperForConditionalGeneration

class AudioEnvModelManager:
    """
    單例模式 (Singleton): 確保環境音效描述模型只實例化一次。
    
    技術核心：
    將音訊感知從「選擇題」提升為「申論題 (Captioning)」。
    採用 MU-NLPC/whisper-tiny-audio-captioning (約 39M 參數)，
    這是基於 Whisper 架構但專門針對「環境音描述 (AudioCaps)」微調的版本。
    推論速度極快，且完美支援 Hugging Face 原生 API，避免自訂模型的報錯。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AudioEnvModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        """
        初始化模型與處理器，並設定硬體加速與半精度。
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 使用真實存在的 Audio Captioning 輕量級模型
        self.model_id = "MU-NLPC/whisper-tiny-audio-captioning" 
        
        self.processor = WhisperProcessor.from_pretrained(self.model_id)
        
        # 強制使用 FP16 精度，以利與 Qwen2-VL 共存於 VRAM
        self.model = WhisperForConditionalGeneration.from_pretrained(
            self.model_id,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
        ).to(self.device)
        
        self.model.eval()

    def get_audio_description(self, audio_path: str) -> str:
        """
        核心方法：輸入音檔路徑，回傳自然語言的環境描述。
        """
        try:
            # Whisper 架構嚴格要求 16000Hz 採樣率
            audio_array, sampling_rate = librosa.load(audio_path, sr=16000)
            
            # 特徵提取並搬移至 GPU
            inputs = self.processor(
                audio_array, 
                sampling_rate=sampling_rate, 
                return_tensors="pt"
            ).to(self.device)

            # 確保輸入特徵也是半精度
            if self.device == "cuda":
                inputs = {k: v.to(torch.float16) if v.is_floating_point() else v for k, v in inputs.items()}

            with torch.no_grad():
                # 生成環境描述
                output_ids = self.model.generate(
                    **inputs, 
                    max_new_tokens=64, # 環境音描述通常很短，限制長度以加速
                    num_beams=3,       # 適度使用 Beam Search 提升流暢度
                    early_stopping=True
                )
                
                # 解碼為純文字
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
        相容性介面：為了不破壞現有 VideoProcessor.py 的 Metadata 串接邏輯。
        """
        description = self.get_audio_description(audio_path)
        # 回傳格式與原 CLAP 保持一致，但標籤改為真實環境描述
        return [{"sound": "environment_description", "caption": description, "score": 1.0}]