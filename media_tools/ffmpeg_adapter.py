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
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=codec_name",
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
            return str(streams[0].get("codec_name", "")).lower()
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
