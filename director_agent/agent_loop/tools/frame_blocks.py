"""
導演看原始畫面的共用抓幀 / image block 工具 (DRY)。

``view_raw``(看使用者素材)與 ``view_template``(看範本影片)都需要同一套:在指定秒數抓幀、降解析、
轉 JPEG base64 image content block,以及「沒給時間點就依切點 / 均勻取樣」的預設取樣。把這套邏輯集中
於此單一模組供兩個工具共用,避免各寫一份而漂移(符合去重 / design pattern 規範)。

重型相依(PIL / cv2)刻意延遲到函式內 import,使本模組在無這些套件的環境仍可被結構性載入。
"""
from __future__ import annotations

import base64
from io import BytesIO

from config.director_config import DIRECTOR_VIEW_RAW_DOWNSCALE_PX

# tool_result image block 的 JPEG MIME 與壓縮品質(control base64 大小 / token)
_JPEG_MEDIA_TYPE = "image/jpeg"
_JPEG_QUALITY = 85


def text_block(text: str) -> dict:
    """組一個 text content block。"""
    return {"type": "text", "text": text}


def image_block(pil_image, downscale_px: int = DIRECTOR_VIEW_RAW_DOWNSCALE_PX) -> dict:
    """把 PIL Image 降解析、轉 JPEG base64,組成 image content block。"""
    image = pil_image.copy()
    image.thumbnail((downscale_px, downscale_px))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": _JPEG_MEDIA_TYPE, "data": data},
    }


def grab_video_frames(abs_path: str, label: str, timestamps: list[float]) -> list[dict]:
    """
    在指定時間點逐一抓幀,回 content blocks(每幀 = text 標註 + image);全抓不到則拋。

    ``label`` 為前綴標註(如素材 id 或「範本」),讓模型知道每張圖是誰的哪一秒。
    """
    from media_processor.pipeline.utils.video_frame_utils import grab_frame_at_time

    blocks: list[dict] = []
    for timestamp in timestamps:
        pil_image = grab_frame_at_time(abs_path, timestamp)
        if pil_image is None:
            continue
        blocks.append(text_block(f"{label} @ {round(timestamp, 2)}s："))
        blocks.append(image_block(pil_image))
    if not blocks:
        raise RuntimeError("所有時間點都抓不到幀")
    return blocks


def resolve_frame_timestamps(requested, cuts, dur, max_frames: int) -> list[float]:
    """
    決定影片要抓幀的秒數(最多 ``max_frames`` 張)。

    給了 ``requested`` 就用(截斷上限);否則優先用場景切點 ``cuts``,再退回 ``dur`` 內均勻取樣,
    最後給起點。``cuts`` / ``dur`` 來源由呼叫端決定(素材 dossier 或範本 handle),本函式不關心出處。
    """
    if requested:
        return [float(t) for t in requested][:max_frames]
    if cuts:
        return [float(t) for t in cuts][:max_frames]
    dur = float(dur or 0.0)
    if dur <= 0:
        return [0.0]
    # 均勻取樣(避開頭尾):dur*(k+1)/(n+1)
    return [round(dur * (k + 1) / (max_frames + 1), 2) for k in range(max_frames)]
