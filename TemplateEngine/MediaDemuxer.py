import subprocess
import os

class MediaDemuxer:
    """
    Adapter Pattern: 封裝 FFmpeg 影音分離邏輯。
    """
    def extract_tracks(self, video_path: str) -> tuple:
        """
        將影片分離為 video_only.mp4 與 audio_only.wav。
        """
        base_path = os.path.splitext(video_path)[0]
        v_out = f"{base_path}_v_only.mp4"
        a_out = f"{base_path}_a_only.wav"

        print(f"[Demuxer] 正在進行影音軌道剝離...")
        
        # 提取無聲影像
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-an", "-c:v", "copy", v_out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 提取高品質單聲道音訊 (16k 為 AI 分析標準)
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", a_out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return v_out, a_out