import cv2
import subprocess
import json
import os
import tempfile
import pillow_heif

from MediaProcessor.MediaStrategy import MediaStrategy
from QwenModelManager import QwenModelManager          # 【引入統一大腦】
from WhisperModelManager import WhisperModelManager    # 語音大腦
from AudioEnvModelManager import AudioEnvModelManager  # 環境音大腦

pillow_heif.register_heif_opener()

class VideoProcessor(MediaStrategy):
    """
    具體策略：處理動態影片。
    重構：移除笨重的 OpenCV 物理防震與抽幀邏輯。
    Qwen2-VL 原生支援影片解析；保留音訊多模態處理管線。
    """
    def __init__(self):
        super().__init__()
        # 初始化三顆大腦 (皆為單例模式)
        self.vision_engine = QwenModelManager()
        self.whisper_engine = WhisperModelManager()
        self.audio_env_engine = AudioEnvModelManager()

    def _get_ffprobe_metadata(self, file_path: str) -> dict:
        """利用 ffprobe 提取時間、GPS 與是否有音軌 (維持不變)"""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", file_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            info = json.loads(result.stdout)
            tags = info.get("format", {}).get("tags", {})
            creation_time = tags.get("creation_time")
            location = tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709")
            has_audio = any(stream.get("codec_type") == "audio" for stream in info.get("streams", []))
            return {"creation_time": creation_time, "location": location, "has_audio": has_audio}
        except Exception:
            return {"creation_time": None, "location": None, "has_audio": False}

    def _extract_audio(self, video_path: str, temp_audio_path: str) -> bool:
        """使用 ffmpeg 分離音軌成 WAV 檔 (維持不變)"""
        cmd = [
            "ffmpeg", "-i", video_path, "-vn",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            temp_audio_path, "-y"
        ]
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
            
            # 【新增】擷取影片的原始長寬屬性
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            aspect_ratio = round(width / height, 4) if height > 0 else 0
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            cap.release()

            vlm_result = self.vision_engine.analyze_media(file_path, media_type="video")

            if vlm_result.get("is_blurry", False):
                return {
                    "status": "rejected", 
                    "reason": "VLM judged as too shaky or blurry", 
                    "file": file_path,
                    "vlm_caption": vlm_result.get("caption")
                }

            audio_transcript = {"text": "", "chunks": []}
            env_sounds = []

            if meta_info.get("has_audio"):
                temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temp_audio_path = temp_audio.name
                temp_audio.close()

                if self._extract_audio(file_path, temp_audio_path):
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                    env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            return {
                "status": "success",
                "type": "video",
                "file": file_path,
                "metadata": {
                    "width": width,               # 【新增】
                    "height": height,             # 【新增】
                    "aspect_ratio": aspect_ratio, # 【新增】
                    "duration": duration,
                    "creation_time": meta_info.get("creation_time"),
                    "location_gps": meta_info.get("location"),
                    "visual_caption": vlm_result.get("caption"),
                    "subject_focus": vlm_result.get("subject_focus"), # 【新增】主體座標
                    "audio_transcript": audio_transcript,
                    "environmental_sounds": env_sounds
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass