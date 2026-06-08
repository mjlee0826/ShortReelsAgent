"""
video_frame_utils:影片 Stage 共用的 cv2 取幀 / metadata 輔助函式 (Utility / DRY)。

把「用 cv2 開影片抓 metadata」「抓指定秒數的幀」這幾段會被多個影片 Stage 重複用到的 cv2 boilerplate
集中於此(DecodeVideo 取 metadata+代表幀等)。

邏輯與原 ``AbstractVideoProcessor`` 的 ``_extract_video_metadata`` / ``_extract_middle_frame_pil``
逐字對齊,確保輸出與 legacy 一致。
"""
from __future__ import annotations

from typing import Optional

import cv2
from PIL import Image

from config.media_processor_config import INFERENCE_MAX_SHORT_SIDE
from media_tools.ffmpeg_adapter import FFmpegAdapter

# metadata 數值四捨五入位數(逐字對齊原 _extract_video_metadata)
_ASPECT_RATIO_NDIGITS = 4
_FPS_NDIGITS = 2


def cap_pil_resolution(
    img: Image.Image, max_short_side: int = INFERENCE_MAX_SHORT_SIDE
) -> Image.Image:
    """
    短邊超過 max_short_side 時等比縮放後回傳新圖;否則原圖直接回傳(推論用,不影響輸出品質)。

    純記憶體運算、不回寫檔案。所有模型推論幀的共用降解析度入口,主要修復 4K 幀的 GIL-freeze
    (MediaPipe tflite / Saliency ONNX 在 ~8M px 幀推論時不釋放 GIL)。
    """
    width, height = img.size
    short_side = min(width, height)
    if short_side <= max_short_side:
        return img
    # 以短邊為基準等比縮放,長邊同步縮小,維持原始長寬比
    scale = max_short_side / short_side
    return img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)


def extract_video_metadata(file_path: str, ffmpeg: FFmpegAdapter) -> dict:
    """
    擷取影片基本 metadata(逐字對齊原 ``_extract_video_metadata``)。

    解析度 / FPS / 片長以 cv2 讀取;建立時間與 GPS 由 ffprobe 讀容器標籤(cv2 讀不到容器層 metadata)。
    回傳 dict:width / height / aspect_ratio / fps / duration / creation_time / location_gps。
    """
    cap = cv2.VideoCapture(file_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    duration = float(frame_count) / float(fps) if fps > 0 else 0.0
    aspect_ratio = round(width / height, _ASPECT_RATIO_NDIGITS) if height > 0 else 0.0

    container_meta = ffmpeg.extract_container_metadata(file_path)
    return {
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "fps": round(fps, _FPS_NDIGITS),
        "duration": duration,
        "creation_time": container_meta["creation_time"],
        "location_gps": container_meta["location_gps"],
    }


def grab_frame_at_time(file_path: str, time_sec: float) -> Optional[Image.Image]:
    """
    抓取影片指定時間點的單幀,回傳 RGB PIL Image;失敗回 None(不拋例外)。

    對齊原 ``_extract_middle_frame_pil`` / ``_get_saliency_at_time`` 的抓幀方式(POS_MSEC + read)。
    """
    try:
        cap = cv2.VideoCapture(file_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
        ret, frame = cap.read()
        cap.release()
        if ret:
            # cv2→PIL 後立即降解析度:此函式是代表幀 / SaliencyUnion 三幀 / EventBbox N 幀的共用出口,
            # 改一處即覆蓋所有下游模型推論幀(metadata 另由 cv2 CAP_PROP 讀取,不受影響)
            pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            return cap_pil_resolution(pil_image)
    except Exception as e:
        # 抓幀失敗不致命(下游退預設 / 安全區),印警告協助定位
        print(f"[VideoFrameUtils Warning] 抓幀失敗 (t={time_sec:.1f}s): {e}")
    return None
