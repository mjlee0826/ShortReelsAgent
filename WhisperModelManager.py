import torch
from transformers import pipeline

class WhisperModelManager:
    """
    單例模式 (Singleton): 確保 Whisper 語音辨識模型只實例化一次。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            # 強化單例模式的錯誤處理，邏輯與 QwenModelManager 相同
            cls._instance = super(WhisperModelManager, cls).__new__(cls)
            try:
                cls._instance._initialize()
            except Exception as e:
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.model_id = "openai/whisper-large-v3"
        
        # 使用 transformers 的 pipeline 可以大幅簡化音訊處理邏輯
        self.transcriber = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            device=self.device,
            chunk_length_s=30, # 支援長音檔分塊處理
            return_timestamps=True 
        )

    def transcribe(self, audio_path: str) -> dict:
        """
        輸入音檔路徑，回傳逐字稿與時間戳記。
        """
        try:
            # 【關鍵修復】避開 Hugging Face 'logprobs' 變數缺失的 Bug。
            # 移除 no_speech_threshold，且 whisper-large-v3 已經足夠聰明，
            # 大多數時候即便不加參數也能有效避免幻覺。
            result = self.transcriber(
                audio_path, 
                generate_kwargs={
                    "task": "transcribe",
                    "condition_on_prev_tokens": False
                }
            )
            return {
                "text": result["text"].strip(),
                "chunks": result.get("chunks", [])
            }
        except Exception as e:
            return {"text": "", "error": str(e)}