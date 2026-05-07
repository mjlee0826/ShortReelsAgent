import os
import subprocess
from MediaTools.FFmpegAdapter import FFmpegAdapter

class MediaStandardizer:
    """
    Service Layer: 素材標準化工具。
    確保所有進入 AI 流程的素材都具備網頁友善 (Web-safe) 的編碼與格式。
    """
    def __init__(self):
        self.ffmpeg = FFmpegAdapter()
        # 定義支援預覽的副檔名
        self.web_safe_video_ext = ".mp4"
        self.web_safe_image_ext = ".jpg"

    def standardize_folder(self, folder_path: str):
        """
        遍歷資料夾，對不合規的檔案進行原地轉檔或生成預覽檔。
        """
        print(f"🧹 [Standardizer] 開始掃描並標準化素材: {folder_path}")
        
        all_files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        standardized_count = 0

        for filename in all_files:
            file_path = os.path.join(folder_path, filename)
            ext = os.path.splitext(filename)[1].lower()

            # 策略：如果不是 .mp4 或是 iPhone 的 .mov (HEVC)，統一轉成 H.264 .mp4
            if ext in [".mov", ".avi", ".mkv", ".webm"]:
                new_file_path = os.path.join(folder_path, os.path.splitext(filename)[0] + "_std.mp4")
                if not os.path.exists(new_file_path):
                    print(f"   🎥 正在標準化影片: {filename} -> H.264")
                    # 使用 FFmpegAdapter 轉檔 (c:v libx264 確保網頁相容性)
                    if self._convert_to_h264(file_path, new_file_path):
                        standardized_count += 1
                        # 建議保留原檔或標註，此處我們讓後續流程改用新檔案
            
            # 策略：將 HEIC 轉為 JPG (瀏覽器才看得見)
            elif ext in [".heic", ".heif"]:
                new_file_path = os.path.join(folder_path, os.path.splitext(filename)[0] + "_std.jpg")
                if not os.path.exists(new_file_path):
                    print(f"   📸 正在標準化圖片: {filename} -> JPG")
                    if self._convert_image_to_jpg(file_path, new_file_path):
                        standardized_count += 1

        print(f"✅ [Standardizer] 標準化完成，處理了 {standardized_count} 個檔案。")

    def _convert_to_h264(self, input_path: str, output_path: str) -> bool:
        """呼叫 FFmpeg 進行標準 H.264/AAC 轉檔"""
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k",
                    output_path
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"   ❌ 影片轉檔失敗: {e.stderr.decode(errors='replace')}")
            return False

    def _convert_image_to_jpg(self, input_path: str, output_path: str) -> bool:
        """處理 HEIC 轉 JPG"""
        try:
            from PIL import Image
            import pillow_heif
            heif_file = pillow_heif.read_heif(input_path)
            image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw", heif_file.mode, heif_file.stride)
            image.save(output_path, "JPEG", quality=95)
            return True
        except Exception as e:
            print(f"   ❌ 圖片轉檔失敗: {e}")
            return False