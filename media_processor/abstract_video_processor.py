import os
import cv2
import tempfile
import gc
import torch
from PIL import Image
from abc import abstractmethod
from media_processor.media_strategy import MediaStrategy
# 【新增】匯入 FFmpegAdapter
from media_tools.ffmpeg_adapter import FFmpegAdapter

class AbstractVideoProcessor(MediaStrategy):
    """
    樣板方法模式 (Template Method) + 延遲載入模式 (Lazy Initialization)：
    定義了影片流水線，並根據子類別需求動態決定是否進行「時間碼燒錄」。
    """
    def __init__(self):
        super().__init__()
        self._whisper_engine = None
        self._audio_env_engine = None
        self._vad_engine = None
        self._saliency_engine = None
        
        # 【新增】實例化 FFmpegAdapter
        self._ffmpeg = FFmpegAdapter()
        
        # 新增控制標籤：預設不燒錄時間碼，由子類別決定
        self.requires_timecode = False

    @property
    def whisper_engine(self):
        if self._whisper_engine is None:
            from model.whisper_model_manager import WhisperModelManager    
            self._whisper_engine = WhisperModelManager()
        return self._whisper_engine

    @property
    def audio_env_engine(self):
        if self._audio_env_engine is None:
            from model.audio_env_model_manager import AudioEnvModelManager  
            self._audio_env_engine = AudioEnvModelManager()
        return self._audio_env_engine

    @property
    def vad_engine(self):
        if self._vad_engine is None:
            from model.vad_model_manager import VadModelManager           
            self._vad_engine = VadModelManager()
        return self._vad_engine

    @property
    def saliency_engine(self):
        if self._saliency_engine is None:
            from model.saliency_model_manager import SaliencyModelManager 
            self._saliency_engine = SaliencyModelManager()
        return self._saliency_engine

    def process(self, file_path: str) -> dict:
        temp_audio_path = None
        temp_tc_video_path = None
        
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

            # 1. 燒錄時間碼
            if self.requires_timecode:
                temp_tc_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
                temp_tc_video_path = temp_tc_video.name
                temp_tc_video.close()
                
                # 【修改】使用 Adapter 處理時間碼燒錄
                self._ffmpeg.burn_timecode(file_path, temp_tc_video_path)
            else:
                temp_tc_video_path = file_path # 不需要燒錄時，tc_file_path 直接等同原檔

            # 2. 音訊分析 (抽出獨立音軌)
            temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_audio_path = temp_audio.name
            temp_audio.close()
            
            # 【修改】使用 Adapter 處理音軌分離
            self._ffmpeg.extract_ai_audio(file_path, temp_audio_path)

            audio_transcript = {}
            env_sounds = []
            if os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 1000:
                if self.vad_engine.has_speech(temp_audio_path):
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

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
                    "fps": round(fps, 2),
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
            if self.requires_timecode and temp_tc_video_path and temp_tc_video_path != file_path and os.path.exists(temp_tc_video_path):
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
        except Exception:
            pass
        return {"x_percent": 50.0, "y_percent": 50.0}