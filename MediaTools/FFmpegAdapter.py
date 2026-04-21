import subprocess
import os

class FFmpegAdapter:
    """
    Adapter Pattern: 統籌全系統的 FFmpeg 物理操作。
    提供高品質音訊抽取、快速畫面剝離、視覺時間碼燒錄。
    """
    
    def extract_ai_audio(self, input_path: str, output_path: str):
        """抽取符合 AI 分析標準的 16kHz 單聲道 WAV 檔"""
        print(f"[FFmpeg] 正在提取 AI 專用音軌: {os.path.basename(output_path)}")
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path, 
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", 
            output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def strip_audio_fast(self, input_path: str, output_path: str):
        """無損快速剝離音軌，僅保留影像 (Stream Copy)"""
        print(f"[FFmpeg] 正在執行無損畫面剝離: {os.path.basename(output_path)}")
        subprocess.run([
            "ffmpeg", "-y", "-i", input_path, "-an", "-c:v", "copy", output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def burn_timecode(self, input_path: str, output_path: str):
        """在影片左上角燒錄視覺時間碼 (供 Gemini 深度索引使用)"""
        print(f"[FFmpeg] 正在燒錄視覺時間碼: {os.path.basename(output_path)}")
        
        # 【修改】使用原先 AbstractVideoProcessor 驗證過的指令
        # 確保格式為 float (如 12.345)，並使用 ultrafast 解決 drawtext 造成的重新編碼耗時
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "drawtext=text='%{pts\\:flt}': x=20: y=20: fontsize=h/15: fontcolor=white: box=1: boxcolor=black@0.6",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", 
            output_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)