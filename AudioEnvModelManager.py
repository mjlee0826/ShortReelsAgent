import torch
import librosa
import gc
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
            try:
                cls._instance._initialize()
            except Exception as e:
                # 防呆機制：初始化失敗時清空實例，避免留下半殘物件
                cls._instance = None
                raise e
        return cls._instance

    def _initialize(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_id = "laion/clap-htsat-unfused"
        
        self.processor = ClapProcessor.from_pretrained(self.model_id)
        self.model = ClapModel.from_pretrained(self.model_id).to(self.device)
        
        # 擴充我們在旅遊影片中關注的環境音標籤
        self.candidate_labels = [
            "people talking", "ocean waves", "city traffic", 
            "wind blowing", "dog barking", "music playing", 
            "restaurant noise", "nature sounds", "footsteps", "silence"
        ]

    def classify_environment(self, audio_path: str) -> list:
        """
        輸入音檔路徑，回傳符合的環境音標籤與分數。
        """
        try:
            # 使用 librosa 讀取音檔，並統一採樣率為 48kHz (CLAP 模型預設要求)
            audio_array, sampling_rate = librosa.load(audio_path, sr=48000)
            
            inputs = self.processor(
                text=self.candidate_labels, 
                audio=audio_array, 
                return_tensors="pt", 
                padding=True, 
                sampling_rate=sampling_rate
            ).to(self.device)

            # 加入 torch.no_grad() 避免在推論時計算梯度，可大幅節省 VRAM
            with torch.no_grad():
                outputs = self.model(**inputs)
                logits_per_audio = outputs.logits_per_audio
                probs = logits_per_audio.softmax(dim=-1).detach().cpu().numpy()[0]

            results = []
            for label, prob in zip(self.candidate_labels, probs):
                # 【修改閾值】將原本的 0.15 調降至 0.05，讓微弱的環境音也能被捕獲
                if prob > 0.05: 
                    results.append({"sound": label, "score": float(prob)})
            
            return sorted(results, key=lambda x: x['score'], reverse=True)
            
        except Exception as e:
            # 【取消靜默失敗】把真正的錯誤原因印出來，方便除錯
            print(f"[CLAP Error] 環境音分析失敗: {str(e)}")
            return []
            
        finally:
            # 手動釋放 VRAM，確保下一個影片進來時不會 OOM
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()