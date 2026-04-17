import torch
from transformers import pipeline

class WhisperModelManager:
    """
    單例模式 (Singleton): 確保 Whisper 語音辨識模型只實例化一次。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WhisperModelManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        # 【升級】使用 large-v3 取得最強的語音辨識與抗噪能力
        self.model_id = "openai/whisper-large-v3"
        
        self.transcriber = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            device=self.device,
            chunk_length_s=30,
            return_timestamps=True 
        )

    def transcribe(self, audio_path: str) -> dict:
        try:
            # 【關鍵修復】加入防幻覺參數
            # condition_on_prev_tokens=False: 避免模型因為先前的靜音而開始腦補 YouTube 結尾詞
            # no_speech_threshold=0.6: 信心度低於此值的片段直接捨棄，判定為無人聲
            result = self.transcriber(
                audio_path, 
                generate_kwargs={
                    "task": "transcribe",
                    "condition_on_prev_tokens": False,
                    "no_speech_threshold": 0.6
                }
            )
            return {
                "text": result["text"].strip(),
                "chunks": result.get("chunks", [])
            }
        except Exception as e:
            return {"text": "", "error": str(e)}