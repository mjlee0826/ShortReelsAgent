import os
import cv2
import tempfile
import subprocess
from abc import abstractmethod
from MediaProcessor.MediaStrategy import MediaStrategy
from Model.WhisperModelManager import WhisperModelManager    
from Model.AudioEnvModelManager import AudioEnvModelManager  
from Model.VadModelManager import VadModelManager           

class AbstractVideoProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method Pattern)：
    定義影片處理的標準流水線 (Pipeline)。
    將聽覺解析 (Audio) 與基礎 Metadata 抽取放在父類別統一處理，
    將視覺解析 (Visual) 挖空，強制子類別 (Standard / Dense) 依據自身策略實作。
    """
    def __init__(self):
        super().__init__()
        # 初始化共用的聽覺感知大腦
        self.whisper_engine = WhisperModelManager()
        self.audio_env_engine = AudioEnvModelManager()
        self.vad_engine = VadModelManager()           

    def process(self, file_path: str) -> dict:
        """定義演算法的骨架 (Template Method)，子類別不應覆寫此方法"""
        temp_audio_path = None
        try:
            # 1. 抽取基礎影片 Metadata
            cap = cv2.VideoCapture(file_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = float(frame_count) / float(fps) if fps > 0 else 0.0
            cap.release()

            # 2. 聽覺分析：音畫分離與人聲/環境音辨識
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio_path = temp_audio.name
            temp_audio.close()
            
            # 使用 FFmpeg 快速抽音軌
            subprocess.run(
                ["ffmpeg", "-y", "-i", file_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", temp_audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            audio_transcript = None
            env_sounds = []
            if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 1000:
                # VAD 防呆與 Whisper 逐字稿
                if self.vad_engine.has_speech(temp_audio_path):
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                # 開放世界環境音描述 (已替換為 Whisper-audio-caption)
                env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            # 3. 視覺分析：呼叫抽象方法，由子類別決定要「全局看」還是「切片看」
            visual_metadata = self.analyze_visual_semantics(file_path, duration)

            # 4. 組裝最終結果
            return {
                "status": "success",
                "type": "video",
                "file": file_path,
                "metadata": {
                    "width": width,               
                    "height": height,             
                    "duration": duration,
                    "audio_transcript": audio_transcript, 
                    "environmental_sounds": env_sounds,
                    **visual_metadata # 展開子類別回傳的視覺分析結果
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}
        finally:
            # 清理暫存音軌
            if temp_audio_path and os.path.exists(temp_audio_path):
                try: os.remove(temp_audio_path)
                except OSError: pass

    @abstractmethod
    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        """
        抽象擴充點 (Hook)：
        子類別必須實作這個方法，回傳包含視覺特徵 (caption, scores, action_index 等) 的字典。
        """
        pass