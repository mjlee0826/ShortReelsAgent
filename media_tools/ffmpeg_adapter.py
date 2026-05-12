import subprocess
import os

class FFmpegAdapter:
    """
    Adapter Pattern: 統籌全系統的 FFmpeg 物理操作。
    提供高品質音訊抽取、快速畫面剝離、視覺時間碼燒錄。
    """

    def _run(self, args: list, allow_failure: bool = False, error_prefix: str = "[FFmpeg] 執行失敗"):
        result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not allow_failure and result.returncode != 0:
            raise RuntimeError(f"{error_prefix}: {result.stderr.decode(errors='replace')}")
        return result

    def extract_ai_audio(self, input_path: str, output_path: str):
        """抽取符合 AI 分析標準的 16kHz 單聲道 WAV 檔"""
        print(f"[FFmpeg] 正在提取 AI 專用音軌: {os.path.basename(output_path)}")
        # allow_failure=True：部分影片可能無音軌，ffmpeg 非零退出屬正常情況
        self._run([
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_path
        ], allow_failure=True)

    def strip_audio_fast(self, input_path: str, output_path: str):
        """無損快速剝離音軌，僅保留影像 (Stream Copy)"""
        print(f"[FFmpeg] 正在執行無損畫面剝離: {os.path.basename(output_path)}")
        self._run([
            "ffmpeg", "-y", "-i", input_path, "-an", "-c:v", "copy", output_path
        ], error_prefix="[FFmpeg] 畫面剝離失敗")

    def burn_timecode(self, input_path: str, output_path: str):
        """在影片左上角燒錄視覺時間碼 (供 Gemini 深度索引使用)"""
        print(f"[FFmpeg] 正在燒錄視覺時間碼: {os.path.basename(output_path)}")
        self._run([
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "drawtext=text='%{pts\\:flt}': x=20: y=20: fontsize=h/15: fontcolor=white: box=1: boxcolor=black@0.6",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy",
            output_path
        ], error_prefix="[FFmpeg] 時間碼燒錄失敗")
