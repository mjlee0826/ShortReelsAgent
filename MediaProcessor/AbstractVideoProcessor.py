import os
import cv2
import tempfile
import subprocess
from PIL import Image
from abc import abstractmethod
from MediaProcessor.MediaStrategy import MediaStrategy
from Model.WhisperModelManager import WhisperModelManager    
from Model.AudioEnvModelManager import AudioEnvModelManager  
from Model.VadModelManager import VadModelManager           
from Model.SaliencyModelManager import SaliencyModelManager 

class AbstractVideoProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method)：
    定義了包含「時間碼燒錄 (Timecode Burn-in)」的全新影片流水線。
    """
    def __init__(self):
        super().__init__()
        self.whisper_engine = WhisperModelManager()
        self.audio_env_engine = AudioEnvModelManager()
        self.vad_engine = VadModelManager()           
        self.saliency_engine = SaliencyModelManager()

    def process(self, file_path: str) -> dict:
        temp_audio_path = None
        temp_tc_video_path = None
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
            
            # 使用 pts:flt 產生浮點數秒數 (例如 12.345) 印在左上角
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
                if self.vad_engine.has_speech(temp_audio_path):
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            # 3. 視覺與語意分析：將『燒好時間碼的影片』與『原始路徑』一起傳給子類別
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
        """協助在精確的秒數上抽出 Frame 並計算重心，供子類別填補 Action Index 使用"""
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