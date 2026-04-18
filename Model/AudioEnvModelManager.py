import torch
import librosa
import gc
import os
from transformers import AutoProcessor, AutoModelForSeq2SeqLM

class AudioEnvModelManager:
    """
    單例模式 (Singleton): 確保 WavCaps 環境音效描述模型只實例化一次。
    
    技術核心：
    將音訊感知從「選擇題 (Classification)」提升為「申論題 (Captioning)」。
    採用 HTSAT-BART 架構，參數量約 200M，具備極高的推理速度與環境理解力。
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
        初始化模型與處理器，並設定硬體加速。
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # 使用 WavCaps 預訓練模型，這是在旅遊場景中表現最穩定的輕量級版本
        self.model_id = "nanael-shinn/wavcaps-htsat-bart" 
        
        # 載入處理器
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        
        # 載入模型並強制使用 FP16 精度，以利與 Qwen2-VL 共存於 VRAM
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            self.model_id,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32
        ).to(self.device)
        
        # 切換至評估模式
        self.model.eval()

    def get_audio_description(self, audio_path: str) -> str:
        """
        核心方法：輸入音檔路徑，回傳自然語言的環境描述。
        """
        try:
            # 讀取音檔並重採樣。WavCaps 模型通常要求 32kHz 或 44.1kHz
            # 這裡設定 sr=32000 以符合多數 HTSAT 變體的訓練標準
            audio_array, sampling_rate = librosa.load(audio_path, sr=32000)
            
            # 特徵提取並搬移至 GPU
            inputs = self.processor(
                audio_array, 
                sampling_rate=sampling_rate, 
                return_tensors="pt"
            ).to(self.device)

            # 如果在 CUDA 上執行，確保輸入特徵也是半精度
            if self.device == "cuda":
                inputs = {k: v.to(torch.float16) if v.is_floating_point() else v for k, v in inputs.items()}

            with torch.no_grad():
                # 生成環境描述，設定適當的長度限制以維持推理速度
                output_ids = self.model.generate(
                    **inputs, 
                    max_new_tokens=128, 
                    num_beams=4,      # 使用 Beam Search 提升句子流暢度
                    early_stopping=True
                )
                
                # 解碼為純文字
                caption = self.processor.batch_decode(output_ids, skip_special_tokens=True)[0]
            
            return caption.strip()
            
        except Exception as e:
            print(f"[AudioEnv Error] WavCaps 生成描述失敗: {e}")
            return "Ambient background noise"
        finally:
            # 強制回收 VRAM 片段，避免 Phase 1 批次處理時堆積過多顯存
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def classify_environment(self, audio_path: str) -> list:
        """
        相容性介面：為了不破壞現有 VideoProcessor.py 的 Metadata 串接邏輯。
        將原本的 List[Dict] 格式包裝自然語言描述回傳。
        """
        description = self.get_audio_description(audio_path)
        # 回傳格式與原 CLAP 保持一致，但標籤改為描述內容
        return [{"sound": "environment_description", "caption": description, "score": 1.0}]