import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from config.media_processor_config import STANDARDIZE_MAX_LONG_SIDE, STANDARDIZE_MAX_WORKERS
from media_tools.ffmpeg_adapter import FFmpegAdapter

# 一律轉檔的視訊容器副檔名（非 .mp4：含 iPhone .mov HEVC 與其他非網頁友善容器）
_TRANSCODE_ALWAYS_VIDEO_EXT = (".mov", ".avi", ".mkv", ".webm")
# 需閘控的視訊副檔名（.mp4 已是網頁友善，僅在超過解析度上限時才轉，避免重編碼已合規檔案）
_GATED_VIDEO_EXT = ".mp4"
# HEIC/HEIF 圖片副檔名（瀏覽器不支援，需轉 JPG）
_HEIC_IMAGE_EXT = (".heic", ".heif")
# 標準化輸出檔名標記（已含此標記者跳過，避免 _std_std）
_STD_MARKER = "_std."
# 轉檔中途檔副檔名：刻意用「非媒體白名單」副檔名（見 asset_discovery.SUPPORTED_MEDIA_EXTENSIONS），
# 讓 collect_asset_files 在轉檔進行中不會把這個半成品檔列入素材清單，前端也就 probe 不到它
_TEMP_OUTPUT_SUFFIX = ".mp4.part"
# 中途檔強制以 mp4 muxer 輸出：因副檔名已非 .mp4，ffmpeg 無法從副檔名推斷容器，需顯式指定
_MP4_MUXER = "mp4"


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

    def standardize_folder(self, input_dir: str, output_dir: str):
        """
        掃描 ``input_dir``(raw 原始檔),對不合規者轉檔 / 生成預覽,``_std`` 衍生檔輸出到 ``output_dir``。

        B 方案的分層語意:原始檔留在 raw/(``input_dir``)、標準化衍生檔集中到 standardized/
        (``output_dir``),兩層分離避免原始與衍生混雜造成計數錯亂。``input_dir`` 不存在則直接結束
        (尚未下載任何素材的新專案)。

        並行:每檔的重活都在 ffmpeg / PIL 子行程(subprocess 阻塞時釋放 GIL),故用
        ``ThreadPoolExecutor`` 即可真正並行,不需 multiprocess 的 pickle / spawn 開銷。並行度由
        ``STANDARDIZE_MAX_WORKERS`` 設上限,避免共用機 CPU/RAM 超賣(libx264 單檔本就吃滿多核)。
        每個 worker 回傳「是否實際轉了檔」,在主執行緒彙總計數,避免共享計數器的競態。
        """
        print(f"🧹 [Standardizer] 開始掃描並標準化素材: {input_dir} -> {output_dir}")

        if not os.path.isdir(input_dir):
            print(f"✅ [Standardizer] 來源目錄不存在,無素材可標準化: {input_dir}")
            return

        # 衍生檔輸出目錄先建好(NFS 上 makedirs 對既有目錄為 no-op,安全)
        os.makedirs(output_dir, exist_ok=True)

        all_files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        if not all_files:
            print("✅ [Standardizer] 來源目錄無檔案,無素材可標準化。")
            return

        # 並行度取 min(上限, 檔案數),至少 1;檔案數少時不浪費開執行緒
        max_workers = min(STANDARDIZE_MAX_WORKERS, len(all_files))
        # input/output 目錄對所有 worker 相同,以 partial 綁定,map 只迭代檔名
        standardize_one = partial(self._standardize_one, input_dir=input_dir, output_dir=output_dir)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # map 依序回傳各檔結果(僅 max_workers 個並行);converted 為 True 即計入
            standardized_count = sum(
                1 for converted in executor.map(standardize_one, all_files) if converted
            )

        print(f"✅ [Standardizer] 標準化完成，處理了 {standardized_count} 個檔案。")

    def _standardize_one(self, filename: str, input_dir: str, output_dir: str) -> bool:
        """
        標準化單一檔案(供 ThreadPoolExecutor 並行呼叫):實際轉了檔回 ``True``,跳過 / 失敗回 ``False``。

        策略路由與序列版完全一致:非 .mp4 容器或超解析度 .mp4 轉 H.264、HEIC 轉 JPG;``_std``
        衍生檔已存在即跳過(idempotent),讓增量同步重跑不重轉已標準化的素材。轉檔失敗由
        ``_convert_*`` 內部吞錯並回 False,不會中斷其他 worker。
        """
        file_path = os.path.join(input_dir, filename)
        ext = os.path.splitext(filename)[1].lower()

        # 策略：非 .mp4 容器一律轉 H.264 .mp4；.mp4 僅在長邊超過上限（4K）時才轉（見 _needs_video_standardize）
        if self._needs_video_standardize(ext, filename, file_path):
            new_file_path = os.path.join(output_dir, os.path.splitext(filename)[0] + "_std.mp4")
            # 衍生檔已存在即跳過(idempotent):增量同步重跑時不重轉已標準化的素材
            if not os.path.exists(new_file_path):
                print(f"   🎥 正在標準化影片: {filename} -> H.264")
                # 使用 FFmpegAdapter 轉檔 (c:v libx264 確保網頁相容性)；原始檔保留在 raw/，
                # 後續流程改用 standardized/ 的新檔案
                return self._convert_to_h264(file_path, new_file_path)

        # 策略：將 HEIC 轉為 JPG (瀏覽器才看得見)
        elif ext in _HEIC_IMAGE_EXT:
            new_file_path = os.path.join(output_dir, os.path.splitext(filename)[0] + "_std.jpg")
            if not os.path.exists(new_file_path):
                print(f"   📸 正在標準化圖片: {filename} -> JPG")
                return self._convert_image_to_jpg(file_path, new_file_path)

        return False

    def _needs_video_standardize(self, ext: str, filename: str, file_path: str) -> bool:
        """
        判斷影片是否需要標準化轉檔（Strategy：依容器與解析度決定）。

        - 非 .mp4 容器（.mov/.avi/.mkv/.webm）：一律轉（HEVC/HDR/容器正規化，網頁與 Remotion 相容）。
        - .mp4：僅在長邊超過 STANDARDIZE_MAX_LONG_SIDE（4K 等）時才轉，避免重編碼已合規的 1080p
          造成世代品質損失與上傳延遲；解析度由 ffprobe 讀取，讀不到（回 0）時視為不需轉。
        - 已是 _std 標準化版本：跳過（避免 _std_std）。
        """
        if ext in _TRANSCODE_ALWAYS_VIDEO_EXT:
            return True
        if ext == _GATED_VIDEO_EXT and _STD_MARKER not in filename:
            width, height = self.ffmpeg.probe_dimensions(file_path)
            return max(width, height) > STANDARDIZE_MAX_LONG_SIDE
        return False

    def _convert_to_h264(self, input_path: str, output_path: str) -> bool:
        """
        呼叫 FFmpeg 進行標準 H.264/AAC 轉檔（Web-safe + Remotion 友善 + HDR→SDR 正規化）。

        原子寫入：ffmpeg 先寫到同目錄下的「非媒體副檔名」中途檔，全部寫完（含 +faststart 的
        moov 搬移 pass）後才以 ``os.replace`` 原子改名成最終 ``_std.mp4``。如此 reader（縮圖 /
        asset-detail / 瀏覽器 <video>）只會看到「尚未出現」或「完整檔」，不會 probe 到半成品而噴
        ``moov atom not found``；轉檔中途崩潰（如共用機 OOM）也只留下可被覆蓋的中途檔，不會污染
        最終身分而被 idempotent 檢查永久跳過。中途檔放同一目錄確保 rename 在同一檔案系統內為原子操作。
        """
        output_dir = os.path.dirname(output_path)
        # 中途檔：非媒體副檔名 + 不含 {raw_stem}_std 標記，確保轉檔進行中既不被列入素材清單，
        # 原始檔也仍維持可見（避免素材在自己轉檔期間短暫消失）；mkstemp 保證唯一不撞名
        fd, temp_path = tempfile.mkstemp(
            prefix=".tmp_convert_", suffix=_TEMP_OUTPUT_SUFFIX, dir=output_dir
        )
        os.close(fd)  # ffmpeg 會自行開檔寫入（-y 覆蓋 mkstemp 建立的空檔），此處只需檔名
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    # 色彩空間正規化 + 解析度上限：iPhone 12+ 預設拍 HEVC + HLG (BT.2020) 10-bit HDR，
                    # 若只是 -pix_fmt yuv420p 把畫面降成 8-bit，輸出 mp4 的 color atom 仍會殘留 BT.2020/HLG，
                    # 配上 8-bit 像素就成矛盾組合，Chromium decoder 會直接拋 PIPELINE_ERROR_DISCONNECTED。
                    # zscale + tonemap 走真正的 HDR→SDR 路徑（依賴 libzimg；colorspace 濾鏡不支援 HLG transfer）：
                    #   1. zscale t=linear:npl=100：HLG/PQ → 線性光，HDR 峰值校正到 SDR 100 nits
                    #   2. format=gbrpf32le：切到浮點 GBR，tonemap 必要的中介格式
                    #   3. zscale p=bt709：色域從 BT.2020 換到 BT.709
                    #   4. tonemap=hable:desat=0：用 Hable 演算法把高光壓進 SDR 範圍，不自動降飽和
                    #   5. zscale t=bt709:m=bt709:r=tv：套 BT.709 transfer/matrix/TV-range
                    #   6. scale=1920:1920:decrease:divisible_by=2：把長邊壓到 1920（4K→1080p box），
                    #      順便讓 H.264 從 high@5.x 退回 4.2，避免 Remotion 在 4K@60 做頻繁 seek 時
                    #      Chromium decoder 撐不住而觸發 PIPELINE_ERROR_DISCONNECTED；
                    #      `decrease` 只縮不放，原本就 ≤ 1920 的素材保留原樣
                    #   7. format=yuv420p：最終降成 8-bit yuv420p
                    # 對 SDR 來源也安全（BT.709→linear→back 近似 no-op）。
                    # scale 長邊上限與 _needs_video_standardize 的閘控門檻同源（STANDARDIZE_MAX_LONG_SIDE），避免漂移
                    "-vf", f"zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,scale={STANDARDIZE_MAX_LONG_SIDE}:{STANDARDIZE_MAX_LONG_SIDE}:force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p",
                    "-c:v", "libx264",
                    # CFR：把 iPhone 慣用的 VFR 拉成 CFR，避免 Remotion 因時序錯亂解碼失敗
                    # （沿用 source 平均 FPS，不硬寫數值，60 fps 慢動作素材也不會被砍掉一半畫面）
                    "-fps_mode", "cfr",
                    # 強制輸出端 metadata 也標 BT.709，搭配上面的濾鏡，確保色彩空間從像素到 atom 完全一致
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-c:a", "aac", "-b:a", "128k",
                    # +faststart：把 moov atom 移到檔頭，Remotion 透過 Chromium seek 中段時
                    # 才不會因為先抓不到索引而觸發 PIPELINE_ERROR_DISCONNECTED
                    "-movflags", "+faststart",
                    # 中途檔副檔名非 .mp4，需顯式指定 mp4 muxer，否則 ffmpeg 無法從副檔名推斷容器
                    "-f", _MP4_MUXER,
                    temp_path
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            # 轉檔完整成功才原子改名成最終身分：同目錄 rename 為原子操作，reader 不會看到半成品
            os.replace(temp_path, output_path)
            return True
        except subprocess.CalledProcessError as e:
            # 失敗時清掉中途檔，避免殘留垃圾；最終 _std.mp4 從未出現，idempotent 重跑時會自動重轉
            self._remove_quietly(temp_path)
            print(f"   ❌ 影片轉檔失敗: {e.stderr.decode(errors='replace')}")
            return False

    @staticmethod
    def _remove_quietly(path: str) -> None:
        """刪除中途檔且吞掉檔案不存在等例外（清理用，不應因清理失敗反過來中斷主流程）。"""
        try:
            os.remove(path)
        except OSError:
            pass

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