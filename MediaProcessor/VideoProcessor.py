import cv2
import numpy as np
import subprocess
import json
import os
import tempfile
from PIL import Image
import pillow_heif

from MediaProcessor.MediaStrategy import MediaStrategy
from LightweightVideoModelManager import LightweightVideoModelManager
from WhisperModelManager import WhisperModelManager      # 新增: 語音大腦
from AudioEnvModelManager import AudioEnvModelManager  # 新增: 環境音大腦

pillow_heif.register_heif_opener()

class VideoProcessor(MediaStrategy):
    """
    具體策略：處理動態影片。
    Phase 1 升級：多模態特徵萃取 (動態影像 + 人聲辨識 + 環境音分類)
    """
    def __init__(self):
        super().__init__()
        # 初始化影片需要的多模態 AI 引擎 (皆為單例模式)
        self.video_caption_engine = LightweightVideoModelManager()
        self.whisper_engine = WhisperModelManager()
        self.audio_env_engine = AudioEnvModelManager()

    def _get_ffprobe_metadata(self, file_path: str) -> dict:
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
            
            # 檢查是否有音訊軌道
            has_audio = any(stream.get("codec_type") == "audio" for stream in info.get("streams", []))
            
            return {"creation_time": creation_time, "location": location, "has_audio": has_audio}
        except Exception:
            return {"creation_time": None, "location": None, "has_audio": False}

    def _extract_audio(self, video_path: str, temp_audio_path: str) -> bool:
        """
        使用 ffmpeg 將影片的音軌抽離成 16kHz 單聲道的 wav 檔案。
        這是多數聲音模型 (Whisper) 最標準的輸入格式。
        """
        cmd = [
            "ffmpeg", "-i", video_path, "-vn", # -vn 代表不處理影像
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", # 16kHz, 單聲道
            temp_audio_path, "-y" # -y 代表覆蓋已存在的檔案
        ]
        try:
            # 隱藏 ffmpeg 的輸出訊息
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _analyze_motion_and_blur(self, cap: cv2.VideoCapture, total_frames: int) -> tuple:
        """光流法手震分析與模糊度分析 (維持原有邏輯)"""
        start_frame = max(0, int(total_frames / 2) - 5)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ret, prev_frame = cap.read()
        if not ret: return 1000, 0 

        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        blur_scores = [cv2.Laplacian(prev_gray, cv2.CV_64F).var()]
        shake_scores = []

        for _ in range(10):
            ret, curr_frame = cap.read()
            if not ret: break
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
            blur_scores.append(cv2.Laplacian(curr_gray, cv2.CV_64F).var())
            flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            shake_scores.append(np.mean(mag)) 
            prev_gray = curr_gray

        return float(np.mean(blur_scores)), float(np.mean(shake_scores))

    def _extract_uniform_frames(self, cap: cv2.VideoCapture, total_frames: int, num_frames: int = 8) -> list[Image.Image]:
        """均勻提取影格供視覺模型使用 (維持原有邏輯)"""
        frames = []
        if total_frames == 0: return frames
        step = max(1, total_frames // num_frames)
        for i in range(num_frames):
            frame_idx = i * step
            if frame_idx >= total_frames: break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                frames.append(pil_image)
        return frames

    def process(self, file_path: str) -> dict:
        temp_audio_path = None
        try:
            # 1. 取得 Metadata 並確認是否有音訊軌
            meta_info = self._get_ffprobe_metadata(file_path)

            # 2. 視覺分析初始化
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return {"status": "error", "file": file_path, "message": "Failed to read video"}

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            # 3. 物理動態偵測 (剔除廢片)
            avg_blur, avg_shake = self._analyze_motion_and_blur(cap, total_frames)
            if avg_shake > 5.0 or avg_blur < 50:
                cap.release()
                return {"status": "rejected", "reason": "too shaky or blurry", "file": file_path}

            # 4. 視覺連續動作解析
            sampled_frames = self._extract_uniform_frames(cap, total_frames, num_frames=6)
            video_caption = self.video_caption_engine.generate_caption(sampled_frames)
            cap.release()

            # 5. 音訊特徵萃取 (Phase 1 核心升級)
            audio_transcript = {"text": "", "chunks": []}
            env_sounds = []

            if meta_info.get("has_audio"):
                # 建立暫存檔名來儲存抽離出的音檔
                temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temp_audio_path = temp_audio.name
                temp_audio.close()

                if self._extract_audio(file_path, temp_audio_path):
                    # 5a. 人聲辨識 (Whisper)
                    audio_transcript = self.whisper_engine.transcribe(temp_audio_path)
                    # 5b. 環境音分類 (CLAP)
                    env_sounds = self.audio_env_engine.classify_environment(temp_audio_path)

            return {
                "status": "success",
                "type": "video",
                "file": file_path,
                "metadata": {
                    "duration": duration,
                    "creation_time": meta_info.get("creation_time"),
                    "location_gps": meta_info.get("location"),
                    "blur_score": avg_blur,
                    "shake_magnitude": avg_shake,
                    "visual_caption": video_caption,
                    "audio_transcript": audio_transcript, # 包含人聲逐字稿
                    "environmental_sounds": env_sounds  # 包含環境音分析
                }
            }
        except Exception as e:
            return {"status": "error", "file": file_path, "message": str(e)}
        finally:
            # 確保最後一定會刪除暫存的音檔，避免硬碟空間爆炸
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass