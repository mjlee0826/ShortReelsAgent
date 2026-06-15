"""
影片轉檔的編碼後端策略 (Strategy Pattern)。

把「輸入端硬解參數、-vf 濾鏡鏈、輸出端編碼參數」這三段「隨後端（libx264 / NVENC）與來源色彩
（SDR / HDR）而異」的細節，封裝成可互換的策略物件，讓 MediaStandardizer 不必感知 CPU/GPU 差異。
共用的濾鏡片段（縮放尾段、HDR→SDR tonemap 前段）以模組級函式集中，避免兩後端各寫一份而 drift。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from config.media_processor_config import (
    STANDARDIZE_AUDIO_BITRATE,
    STANDARDIZE_NVENC_CQ,
    STANDARDIZE_NVENC_PRESET,
    STANDARDIZE_X264_CRF,
    STANDARDIZE_X264_PRESET,
    STANDARDIZE_X264_THREADS,
)

# CUDA 硬解的 ffmpeg 輸入旗標：解碼在 GPU、且讓影格留在 GPU 顯存（output_format cuda），
# 供 scale_cuda 直接取用、最終由 h264_nvenc 直接編碼，全程不把影格搬回系統記憶體。
_HWACCEL_CUDA_ARGS = ("-hwaccel", "cuda", "-hwaccel_output_format", "cuda")


@dataclass(frozen=True)
class VideoFilterSpec:
    """
    描述一次影片轉檔所需的濾鏡輸入條件（純資料結構，無行為）。

    - is_hdr：來源 transfer 是否為真 HDR（HLG/PQ）。決定是否需走 zscale+tonemap 的 HDR→SDR 重映射；
      未標記色彩的 SDR 來源走該路徑會以 "no path between colorspaces" 失敗，故必須分流。
    - max_long_side：縮放長邊上限（只縮不放）。
    """
    is_hdr: bool
    max_long_side: int


def _scale_and_pack(max_long_side: int) -> str:
    """
    CPU 濾鏡的共同尾段：把長邊壓到 ``max_long_side``（只縮不放、長寬保持偶數），再降成 8-bit yuv420p。

    供 libx264 的 SDR / HDR 兩路徑共用。GPU 路徑改用 scale_cuda（見 NvencEncodeStrategy）。
    """
    return (
        f"scale={max_long_side}:{max_long_side}"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p"
    )


def _hdr_tonemap_filter(max_long_side: int) -> str:
    """
    真 HDR（HLG/PQ）來源的 CPU 濾鏡鏈：走 libzimg 的 HDR→SDR 重映射後接縮放尾段。

    若只把 10-bit HDR 畫面降 8-bit 而不重映射色彩，輸出 mp4 的 color atom 仍殘留 BT.2020/HLG，
    配 8-bit 像素成矛盾組合，Chromium decoder 會拋 PIPELINE_ERROR_DISCONNECTED。步驟：
      1. zscale t=linear:npl=100：HLG/PQ → 線性光，HDR 峰值校正到 SDR 100 nits（npl 為 SDR 參考白）
      2. format=gbrpf32le：切到浮點 GBR，tonemap 必要的中介格式
      3. zscale p=bt709：色域從 BT.2020 換到 BT.709
      4. tonemap=hable:desat=0：用 Hable 演算法把高光壓進 SDR 範圍，不自動降飽和
      5. zscale t=bt709:m=bt709:r=tv：套 BT.709 transfer/matrix/TV-range
    （colorspace 濾鏡不支援 HLG transfer，故必須走 zscale/libzimg。）
    """
    return (
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
        f"{_scale_and_pack(max_long_side)}"
    )


class VideoEncodeStrategy(ABC):
    """影片編碼後端的抽象策略：封裝隨後端而異的輸入旗標、濾鏡鏈與編碼參數。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """後端顯示名稱（日誌與回退訊息用，如 'libx264'、'NVENC'）。"""

    @abstractmethod
    def input_args(self, spec: VideoFilterSpec) -> list[str]:
        """``-i`` 之前的輸入端旗標（如 CUDA 硬解）；CPU 後端通常為空。"""

    @abstractmethod
    def build_video_filter(self, spec: VideoFilterSpec) -> str:
        """依來源色彩與後端組出 ``-vf`` 濾鏡鏈字串。"""

    @abstractmethod
    def codec_args(self) -> list[str]:
        """輸出端視訊編碼參數（編碼器、preset、品質、緒數等）。"""


class X264EncodeStrategy(VideoEncodeStrategy):
    """
    CPU 軟體編碼後端（libx264）：標準化的預設後端。

    無硬解輸入旗標；濾鏡全在 CPU——SDR 走輕量縮放、HDR 走 zscale+tonemap。輸出以 veryfast preset +
    固定 CRF + 每檔緒數上限編碼（見 config 常數），兼顧速度與多檔並行下的核心分配。
    """

    @property
    def name(self) -> str:
        return "libx264"

    def input_args(self, spec: VideoFilterSpec) -> list[str]:
        # CPU 解碼，無硬解旗標
        return []

    def build_video_filter(self, spec: VideoFilterSpec) -> str:
        if spec.is_hdr:
            return _hdr_tonemap_filter(spec.max_long_side)
        return _scale_and_pack(spec.max_long_side)

    def codec_args(self) -> list[str]:
        return [
            "-c:v", "libx264",
            "-preset", STANDARDIZE_X264_PRESET,
            "-crf", STANDARDIZE_X264_CRF,
            "-threads", STANDARDIZE_X264_THREADS,
        ]


class NvencEncodeStrategy(VideoEncodeStrategy):
    """
    GPU 硬體編碼後端（h264_nvenc，RTX 30 系的 NVENC ASIC）：選用後路，預設關閉。

    SDR 來源走全 GPU 管線（CUDA 硬解 → scale_cuda 顯存內縮放 → NVENC 直接編碼），CPU 幾乎不參與。
    真 HDR 來源因 tonemap（libzimg）只能在 CPU 跑，改走 CPU 解碼 + CPU zscale 濾鏡，再交由 NVENC
    編碼（NVENC 可吃系統記憶體影格、內部自行上傳）——仍享 GPU 編碼之利，僅放棄該（少見）路徑的硬解。
    """

    # NVENC 的 H.264 編碼器名稱：codec_args 與「ffmpeg 是否 build 此編碼器」的可用性檢查共用單一來源
    ENCODER_NAME = "h264_nvenc"

    @property
    def name(self) -> str:
        return "NVENC"

    def input_args(self, spec: VideoFilterSpec) -> list[str]:
        # HDR 需 CPU tonemap，影格不可留在顯存，故不加 CUDA 硬解旗標
        if spec.is_hdr:
            return []
        # SDR：全 GPU 管線，硬解並讓影格留在 GPU 供 scale_cuda 使用
        return list(_HWACCEL_CUDA_ARGS)

    def build_video_filter(self, spec: VideoFilterSpec) -> str:
        if spec.is_hdr:
            # HDR 走與 CPU 後端相同的 zscale+tonemap 鏈（在系統記憶體上）
            return _hdr_tonemap_filter(spec.max_long_side)
        # SDR：在 GPU 上以 scale_cuda 縮放並直接輸出 yuv420p，免把影格搬回 CPU
        return (
            f"scale_cuda={spec.max_long_side}:{spec.max_long_side}"
            ":force_original_aspect_ratio=decrease:force_divisible_by=2:format=yuv420p"
        )

    def codec_args(self) -> list[str]:
        # -cq 為 NVENC 的固定品質模式（語意近 libx264 的 CRF）
        return [
            "-c:v", self.ENCODER_NAME,
            "-preset", STANDARDIZE_NVENC_PRESET,
            "-cq", STANDARDIZE_NVENC_CQ,
        ]


# 共用：標準化轉檔對所有後端皆相同的輸出端旗標（與後端/色彩無關），集中於此供命令組裝引用。
def common_output_args(mp4_muxer: str, output_path: str) -> list[str]:
    """
    組出與編碼後端無關的共同輸出參數：CFR、強制標 BT.709 色彩、AAC 音訊、faststart、mp4 muxer。

    - -fps_mode cfr：把 iPhone 慣用的 VFR 拉成 CFR，避免 Remotion 因時序錯亂解碼失敗。
    - -color_primaries/-color_trc/-colorspace bt709：強制輸出 color atom 標 BT.709，與濾鏡輸出一致；
      也替「未標記色彩」的 SDR 來源補上正確標記。
    - -movflags +faststart：moov atom 移到檔頭，利 Remotion 透過 Chromium seek 中段。
    - -f：中途檔副檔名非 .mp4，需顯式指定 mp4 muxer。
    """
    return [
        "-fps_mode", "cfr",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", STANDARDIZE_AUDIO_BITRATE,
        "-movflags", "+faststart",
        "-f", mp4_muxer,
        output_path,
    ]
