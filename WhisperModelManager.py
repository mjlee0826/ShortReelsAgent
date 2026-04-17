import torch
from transformers import pipeline

class WhisperModelManager:
    """
    單例模式 (Singleton): 確保 Whisper 語音辨識模型只實例化一次。
    用於將影片中的人聲轉換為帶有時間戳記的文字 (Transcript)。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WhisperModelManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        # 使用 small 版本以在本地端取得效能與準確度的平衡
        self.model_id = "openai/whisper-small"
        
        # 使用 transformers 的 pipeline 可以大幅簡化音訊處理邏輯
        self.transcriber = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            device=self.device,
            chunk_length_s=30, # 支援長音檔分塊處理
            return_timestamps=True # 開啟時間戳記功能
        )

    def transcribe(self, audio_path: str) -> dict:
        """
        輸入音檔路徑，回傳逐字稿與時間戳記。
        如果影片沒有人講話，回傳空字串。
        """
        try:
            # 讓 Whisper 自動偵測語言並進行辨識
            result = self.transcriber(audio_path, generate_kwargs={"task": "transcribe"})
            return {
                "text": result["text"].strip(),
                "chunks": result.get("chunks", []) # 包含每個句子的開始與結束時間
            }
        except Exception as e:
            return {"text": "", "error": str(e)}