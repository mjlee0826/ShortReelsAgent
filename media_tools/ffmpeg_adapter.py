"""FFmpeg 操作的統一介面，封裝所有底層 shell 呼叫。"""

import os
import json
import subprocess

from config.media_processor_config import (
    TIMECODE_FONT_SIZE_EXPR,
    TIMECODE_POSITION_X,
    TIMECODE_POSITION_Y,
)
from config.model_config import AUDIO_SAMPLING_RATE

# 影片容器中可能存放 GPS 座標的標籤名稱，依優先順序嘗試
_GPS_TAG_CANDIDATES = (
    "com.apple.quicktime.location.ISO6709",  # iPhone 影片
    "location",
    "location-eng",
)


class FFmpegAdapter:
    """
    配接器模式 (Adapter Pattern)：統籌全系統的 FFmpeg 物理操作。
    提供高品質音訊抽取、快速畫面剝離、視覺時間碼燒錄三項核心功能，
    所有 subprocess 呼叫集中在此，其他模組不直接執行 ffmpeg 指令。
    """

    def __init__(self) -> None:
        """初始化配接器；編碼器支援度查詢結果以此快取，避免每檔重複 spawn ffmpeg。"""
        # 編碼器名稱 -> 是否被目前 ffmpeg build 支援（supports_encoder 的記憶化快取）
        self._encoder_support_cache: dict[str, bool] = {}

    def supports_encoder(self, encoder_name: str) -> bool:
        """
        檢查目前 ffmpeg build 是否含指定編碼器（如 'h264_nvenc'）。

        以 ``ffmpeg -encoders`` 輸出做名稱比對，供 MediaStandardizer 決定能否啟用 NVENC 硬體編碼。
        查詢結果以實例快取（記憶化），避免每檔重複 spawn ffmpeg。無 ffmpeg／查詢失敗時回 False
        （安全降級為「不支援」，呼叫端自動改用 CPU 編碼）。
        """
        if encoder_name in self._encoder_support_cache:
            return self._encoder_support_cache[encoder_name]
        supported = False
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                supported = encoder_name in result.stdout.decode(errors="replace")
        except OSError:
            supported = False
        self._encoder_support_cache[encoder_name] = supported
        return supported

    def _run(
        self,
        args: list[str],
        allow_failure: bool = False,
        error_prefix: str = "[FFmpeg] 執行失敗",
    ) -> subprocess.CompletedProcess:
        """
        執行 FFmpeg 子程序並處理錯誤。
        allow_failure=True 時允許非零退出碼（例如靜音影片的音訊抽取）。
        """
        result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if not allow_failure and result.returncode != 0:
            raise RuntimeError(f"{error_prefix}: {result.stderr.decode(errors='replace')}")
        return result

    def extract_ai_audio(self, input_path: str, output_path: str) -> None:
        """
        抽取符合 AI 分析標準的單聲道 WAV 檔。
        採樣率固定為 AUDIO_SAMPLING_RATE（Whisper/VAD/AudioEnv 共同要求）。
        allow_failure=True：部分影片無音軌，ffmpeg 非零退出屬正常情況。
        """
        print(f"[FFmpeg] 正在提取 AI 專用音軌: {os.path.basename(output_path)}")
        self._run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", str(AUDIO_SAMPLING_RATE),
                "-ac", "1",
                output_path,
            ],
            allow_failure=True,
        )

    def extract_container_metadata(self, input_path: str) -> dict:
        """
        以 ffprobe 讀取影片容器標籤，擷取建立時間與 GPS 座標。
        cv2 無法讀取容器層 metadata，故改用 ffprobe 的 -show_format。
        擷取失敗（無 ffprobe、檔案損壞、無對應標籤）時靜默回傳空字串，不阻斷主流程。
        """
        metadata = {"creation_time": "", "location_gps": ""}
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    input_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return metadata

            tags = json.loads(result.stdout).get("format", {}).get("tags", {})
            metadata["creation_time"] = tags.get("creation_time", "")
            # GPS 標籤名稱因裝置而異，依候選清單依序嘗試
            for tag_name in _GPS_TAG_CANDIDATES:
                if tags.get(tag_name):
                    metadata["location_gps"] = tags[tag_name]
                    break
        except (json.JSONDecodeError, OSError, KeyError):
            pass
        return metadata

    def probe_dimensions(self, input_path: str) -> tuple[int, int]:
        """
        以 ffprobe 讀取第一條視訊串流的像素寬高，回傳 (width, height)。
        供 MediaStandardizer 判斷 .mp4 是否需降解析度轉檔（例如 4K）。
        讀取失敗（無 ffprobe、無視訊串流、檔案損壞）時靜默回傳 (0, 0)，
        由呼叫端視為「不需轉檔」安全降級，不阻斷主流程。
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-print_format", "json",
                    input_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return (0, 0)
            streams = json.loads(result.stdout).get("streams", [])
            if not streams:
                return (0, 0)
            return (int(streams[0].get("width", 0)), int(streams[0].get("height", 0)))
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            return (0, 0)

    def probe_codec(self, input_path: str) -> str:
        """
        以 ffprobe 讀取第一條視訊串流的『實際編碼名稱』（小寫，如 'h264'、'hevc'）。

        供 MediaStandardizer 判斷「副檔名雖為 .mp4、實際卻是非網頁友善編碼（如 iPhone HEVC，
        常見於名為 IMG_xxxx.MOV.mp4 的檔）」：這類檔的 .MOV 被 .mp4 後綴蓋過而鑽過「.mov 一律轉」
        的規則，需改看『實際內容(codec)』而非副檔名（與圖片端 PIL 內容嗅探同 philosophy）。
        讀取失敗（無 ffprobe／無視訊串流／檔案損壞）時回空字串，由呼叫端視為『不確定』安全降級
        （不因偶發讀取失敗而誤判成需轉檔）。
        """
        return self._probe_stream_entry(input_path, "codec_name")

    def probe_color_transfer(self, input_path: str) -> str:
        """
        以 ffprobe 讀取第一條視訊串流的『色彩轉移特性 (transfer characteristics)』
        （小寫，如 'bt709'、'arib-std-b67'(HLG)、'smpte2084'(PQ)）。

        供 MediaStandardizer 判斷來源是否為『真 HDR』：只有 HLG/PQ 來源才需要走 zscale+tonemap
        的 HDR→SDR 重映射。SDR——尤其是『未標記色彩 (untagged)』的來源——若誤走該路徑，zscale
        因找不到輸入 transfer 可錨定，會對每一影格以 "no path between colorspaces" (code 3074)
        失敗。讀不到（無 ffprobe／無視訊串流／來源根本未標記 transfer）時回空字串，由呼叫端視為
        『非 HDR』安全降級（走輕量縮放路徑，不做 tonemap）。
        """
        return self._probe_stream_entry(input_path, "color_transfer")

    def _probe_stream_entry(self, input_path: str, entry: str) -> str:
        """
        以 ffprobe 讀取第一條視訊串流的單一字串欄位（轉小寫），供各 probe_* 共用的私有樣板。

        集中 ffprobe 呼叫與例外處理，避免每個 probe_* 重複相同樣板（DRY）。讀取失敗
        （無 ffprobe／無視訊串流／檔案損壞／串流無此欄位）一律回空字串，由各呼叫端依語意安全降級。
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-select_streams", "v:0",
                    "-show_entries", f"stream={entry}",
                    "-print_format", "json",
                    input_path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                return ""
            streams = json.loads(result.stdout).get("streams", [])
            if not streams:
                return ""
            return str(streams[0].get(entry, "")).lower()
        except (json.JSONDecodeError, OSError, KeyError):
            return ""

    def strip_audio_fast(self, input_path: str, output_path: str) -> None:
        """無損快速剝離音軌，僅保留影像（Stream Copy，速度極快）。"""
        print(f"[FFmpeg] 正在執行無損畫面剝離: {os.path.basename(output_path)}")
        self._run(
            ["ffmpeg", "-y", "-i", input_path, "-an", "-c:v", "copy", output_path],
            error_prefix="[FFmpeg] 畫面剝離失敗",
        )

    def burn_timecode(self, input_path: str, output_path: str) -> None:
        """
        在影片左上角燒錄視覺時間碼（供 Gemini 深度索引使用）。
        時間碼格式為浮點秒數，字體大小與位置由 media_processor_config 常數控制。
        """
        print(f"[FFmpeg] 正在燒錄視覺時間碼: {os.path.basename(output_path)}")
        vf_filter = (
            f"drawtext=text='%{{pts\\:flt}}'"
            f": x={TIMECODE_POSITION_X}"
            f": y={TIMECODE_POSITION_Y}"
            f": fontsize={TIMECODE_FONT_SIZE_EXPR}"
            f": fontcolor=white"
            f": box=1: boxcolor=black@0.6"
        )
        self._run(
            [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", vf_filter,
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy",
                output_path,
            ],
            error_prefix="[FFmpeg] 時間碼燒錄失敗",
        )
