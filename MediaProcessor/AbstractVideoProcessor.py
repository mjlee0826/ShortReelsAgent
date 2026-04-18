import os
import cv2
import tempfile
import subprocess
import numpy as np
from PIL import Image
from abc import abstractmethod
from MediaProcessor.MediaStrategy import MediaStrategy
from Model.WhisperModelManager import WhisperModelManager    
from Model.AudioEnvModelManager import AudioEnvModelManager  
from Model.VadModelManager import VadModelManager           
from Model.SaliencyModelManager import SaliencyModelManager 

class AbstractVideoProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method Pattern)：
    將聽覺解析、基礎 Metadata 抽取與「顯著性重心計算」等共通邏輯放在父類別處理。 
    """
    def __init__(self):
        super().__init__()
        # 初始化共用的聽覺與物理感知大腦
        self.whisper_engine = WhisperModelManager()
        self.audio_env_engine = AudioEnvModelManager()
        self.vad_engine = VadModelManager()           
        self.saliency_engine = SaliencyModelManager() # 共通的重心偵測大腦 

    def _calculate_saliency_focus(self, pil_image: Image.Image) -> dict:
        """
        共通邏輯：使用 U2-Net 遮罩計算主體重心的百分比座標。
        這能協助 Phase 5 的 Remotion 進行 9:16 的智慧裁切。 [cite: 15, 28]
        """
        try:
            mask = self.saliency_engine.get_saliency_mask(pil_image)
            M = cv2.moments(mask)
            if M["m00"] != 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                width, height = pil_image.size
                return {
                    "x_percent": round((cX / width) * 100, 1),
                    "y_percent": round((cY / height) * 100, 1)
                }
        except Exception as e:
            print(f"[Saliency Calculation Error]: {e}")
            
        return {"x_percent": 50.0, "y_percent": 50.0}

    def process(self, file_path: str) -> dict:
        """定義演算法的骨架 (Template Method)"""
        temp_audio_path = None
        try:
            cap = cv2.VideoCapture(file_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = float(frame_count) / float(fps) if fps > 0 else 0.0
            cap.release()

            # 音訊分析邏輯
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio_path = temp_audio.name
            temp_audio.close()
            
            subprocess.run(
                ["ffmpeg", "-y", "-i", file_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", temp_audio_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            audio_transcript = None
            env_sounds = []
            if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 1000:
                if self.vad_engine.has_speech(temp_audio_path):
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            # 呼叫子類別實作的視覺分析
            visual_metadata = self.analyze_visual_semantics(file_path, duration)

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
                    **visual_metadata 
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try: os.remove(temp_audio_path)
                except OSError: pass

    @abstractmethod
    def analyze_visual_semantics(self, file_path: str, duration: float) -> dict:
        pass