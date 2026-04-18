import cv2
import subprocess
import json
import os
import tempfile
from PIL import Image
import pillow_heif

from MediaProcessor.MediaStrategy import MediaStrategy
from QwenModelManager import QwenModelManager          
from WhisperModelManager import WhisperModelManager    
from AudioEnvModelManager import AudioEnvModelManager  
from SaliencyModelManager import SaliencyModelManager
from VadModelManager import VadModelManager

pillow_heif.register_heif_opener()

class VideoProcessor(MediaStrategy):
    """具體策略：處理動態影片"""
    def __init__(self):
        super().__init__()
        self.vision_engine = QwenModelManager()
        self.whisper_engine = WhisperModelManager()
        self.audio_env_engine = AudioEnvModelManager()
        self.saliency_engine = SaliencyModelManager()
        self.vad_engine = VadModelManager()

    def _get_ffprobe_metadata(self, file_path: str) -> dict:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            info = json.loads(result.stdout)
            tags = info.get("format", {}).get("tags", {})
            return {
                "creation_time": tags.get("creation_time"),
                "location": tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709"),
                "has_audio": any(stream.get("codec_type") == "audio" for stream in info.get("streams", []))
            }
        except Exception:
            return {"creation_time": None, "location": None, "has_audio": False}

    def _extract_audio(self, video_path: str, temp_audio_path: str) -> bool:
        cmd = ["ffmpeg", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", temp_audio_path, "-y"]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def process(self, file_path: str) -> dict:
        temp_audio_path = None
        try:
            meta_info = self._get_ffprobe_metadata(file_path)

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return {"status": "error", "file": file_path, "message": "Failed to read video"}
            
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            aspect_ratio = round(width / height, 4) if height > 0 else 0
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            # 【核心邏輯 1】抽取影片中段畫面，進行顯著性與模糊度運算
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames // 2))
            ret, frame = cap.read()
            cap.release()

            subject_focus = {"x": 50, "y": 50}
            if ret:
                pil_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                mask = self.saliency_engine.get_saliency_mask(pil_frame)
                
                # 計算主體重心
                M = cv2.moments(mask)
                if M["m00"] != 0:
                    subject_focus = {
                        "x": int((M["m10"] / M["m00"]) / width * 100), 
                        "y": int((M["m01"] / M["m00"]) / height * 100)
                    }

                # Saliency-Masked Laplacian
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                laplacian = cv2.Laplacian(gray, cv2.CV_64F)
                masked_laplacian = laplacian[mask > 128]
                blur_score = masked_laplacian.var() if len(masked_laplacian) > 0 else laplacian.var()

                if blur_score < 50:
                    return {
                        "status": "rejected", 
                        "reason": f"Saliency-Masked Blur (score: {blur_score:.1f})", 
                        "file": file_path
                    }

            # 呼叫 Qwen 生成語意
            vlm_result = self.vision_engine.analyze_media(file_path, media_type="video")

            audio_transcript = {"text": "", "chunks": []}
            env_sounds = []

            if meta_info.get("has_audio"):
                temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temp_audio_path = temp_audio.name
                temp_audio.close()

                if self._extract_audio(file_path, temp_audio_path):
                    # 【核心邏輯 2】VAD 守門員：先確認有人聲，才呼叫 Whisper
                    if self.vad_engine.has_speech(temp_audio_path):
                        audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                    
                    # 環境音不受人聲影響，一律進行分析
                    env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            return {
                "status": "success",
                "type": "video",
                "file": file_path,
                "metadata": {
                    "width": width,               
                    "height": height,             
                    "aspect_ratio": aspect_ratio, 
                    "duration": duration,
                    "creation_time": meta_info.get("creation_time"),
                    "location_gps": meta_info.get("location"),
                    "visual_caption": vlm_result.get("caption"),
                    "subject_focus": subject_focus, # 【精準座標】
                    "audio_transcript": audio_transcript, # 【已根除幻覺】
                    "environmental_sounds": env_sounds
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try: os.remove(temp_audio_path)
                except OSError: pass