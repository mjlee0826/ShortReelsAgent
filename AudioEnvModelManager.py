import torch
import librosa
from transformers import ClapModel, ClapProcessor

class AudioEnvModelManager:
    """
    單例模式 (Singleton): 確保 CLAP 環境音效模型只實例化一次。
    用於分析音檔，給出環境聲音的標籤與信心度。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AudioEnvModelManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "laion/clap-htsat-unfused"
        
        self.processor = ClapProcessor.from_pretrained(self.model_id)
        self.model = ClapModel.from_pretrained(self.model_id).to(self.device)
        
        # 預先定義我們在旅遊影片中關注的環境音標籤
        self.candidate_labels = [
            "people talking", "ocean waves", "city traffic", 
            "wind blowing", "dog barking", "music playing", 
            "restaurant noise", "nature sounds"
        ]

    def classify_environment(self, audio_path: str) -> list:
        """
        輸入音檔路徑，回傳符合的環境音標籤與分數。
        """
        try:
            # 使用 librosa 讀取音檔，並統一採樣率為 48kHz (CLAP 預設)
            audio_array, sampling_rate = librosa.load(audio_path, sr=48000)
            
            inputs = self.processor(
                text=self.candidate_labels, 
                audios=audio_array, 
                return_tensors="pt", 
                padding=True, 
                sampling_rate=sampling_rate
            ).to(self.device)

            outputs = self.model(**inputs)
            # 計算音訊與各個文字標籤的相似度機率
            logits_per_audio = outputs.logits_per_audio
            probs = logits_per_audio.softmax(dim=-1).detach().cpu().numpy()[0]

            results = []
            for label, prob in zip(self.candidate_labels, probs):
                if prob > 0.15: # 設定信心閾值
                    results.append({"sound": label, "score": float(prob)})
            
            return sorted(results, key=lambda x: x['score'], reverse=True)
        except Exception:
            return []