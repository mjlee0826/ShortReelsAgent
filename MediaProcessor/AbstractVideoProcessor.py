import os
import cv2
import tempfile
import subprocess
import gc
import torch
from PIL import Image
from abc import abstractmethod
from MediaProcessor.MediaStrategy import MediaStrategy

class AbstractVideoProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method) + 延遲載入模式 (Lazy Initialization)：
    定義了包含「時間碼燒錄」的影片流水線，並嚴格控管 VRAM 載入時機，防止 OOM。
    """
    def __init__(self):
        super().__init__()
        # 【重構】拔除 __init__ 中的直接實例化，改為 None
        # 這是為了解決 OOM，確保模型「被用到時」才載入 GPU
        self._whisper_engine = None
        self._audio_env_engine = None
        self._vad_engine = None
        self._saliency_engine = None

    # ==========================================
    # 延遲載入 (Lazy Initialization) 屬性區塊
    # ==========================================
    @property
    def whisper_engine(self):
        if self._whisper_engine is None:
            from Model.WhisperModelManager import WhisperModelManager    
            self._whisper_engine = WhisperModelManager()
        return self._whisper_engine

    @property
    def audio_env_engine(self):
        if self._audio_env_engine is None:
            from Model.AudioEnvModelManager import AudioEnvModelManager  
            self._audio_env_engine = AudioEnvModelManager()
        return self._audio_env_engine

    @property
    def vad_engine(self):
        if self._vad_engine is None:
            from Model.VadModelManager import VadModelManager           
            self._vad_engine = VadModelManager()
        return self._vad_engine

    @property
    def saliency_engine(self):
        if self._saliency_engine is None:
            from Model.SaliencyModelManager import SaliencyModelManager 
            self._saliency_engine = SaliencyModelManager()
        return self._saliency_engine

    # ==========================================
    # 核心流水線
    # ==========================================
    def process(self, file_path: str) -> dict:
        temp_audio_path = None
        temp_tc_video_path = None
        
        # 【防禦】執行前先清空可能的殘留 VRAM
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        
        try:
            cap = cv2.VideoCapture(file_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = float(frame_count) / float(fps) if fps > 0 else 0.0
            cap.release()

            # 1. 燒錄時間碼 (Timecode Burn-in) 產生給 VLM 看的專用影片
            temp_tc_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_tc_video_path = temp_tc_video.name
            temp_tc_video.close()
            
            subprocess.run([
                "ffmpeg", "-y", "-i", file_path, 
                "-vf", "drawtext=text='%{pts\\:flt}': x=20: y=20: fontsize=h/15: fontcolor=white: box=1: boxcolor=black@0.6", 
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", 
                temp_tc_video_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 2. 音訊分析 (抽出獨立音軌)
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio_path = temp_audio.name
            temp_audio.close()
            
            subprocess.run([
                "ffmpeg", "-y", "-i", file_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", temp_audio_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            audio_transcript = None
            env_sounds = []
            if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 1000:
                # 透過 property 呼叫，此時才會真正載入模型
                if self.vad_engine.has_speech(temp_audio_path):
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            # 【防禦】音訊處理完畢後，清理不需要的張量，騰出 VRAM 給視覺模組
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

            # 3. 視覺與語意分析
            visual_metadata = self.analyze_visual_semantics(file_path, temp_tc_video_path, duration)

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
            if temp_tc_video_path and os.path.exists(temp_tc_video_path):
                try: os.remove(temp_tc_video_path)
                except OSError: pass

    @abstractmethod
    def analyze_visual_semantics(self, raw_file_path: str, tc_file_path: str, duration: float) -> dict:
        pass

    def _get_saliency_at_time(self, file_path: str, time_sec: float) -> dict:
        try:
            cap = cv2.VideoCapture(file_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
            ret, frame = cap.read()
            cap.release()
            if ret:
                pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                mask = self.saliency_engine.get_saliency_mask(pil_image)
                M = cv2.moments(mask)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    width, height = pil_image.size
                    return {"x_percent": round((cX / width) * 100, 1), "y_percent": round((cY / height) * 100, 1)}
        except Exception as e:
            pass
        return {"x_percent": 50.0, "y_percent": 50.0}