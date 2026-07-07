"""
導演看原始畫面的共用抓幀 / image block 工具 (DRY)。

``view_raw``(看使用者素材)與 ``view_template``(看範本影片)都需要同一套:在指定秒數抓幀、降解析、
轉 JPEG base64 image content block,以及「沒給時間點就依切點 / 均勻取樣」的預設取樣。把這套邏輯集中
於此單一模組供兩個工具共用,避免各寫一份而漂移(符合去重 / design pattern 規範)。

像素 token 預算(montage 拼格)
------------------------------
影片多幀**不再**逐幀送單張大圖(1080px/張 ≈ 900–1500 tokens/張),改拼成一張網格 montage:
每格長邊 ``DIRECTOR_VIEW_RAW_MONTAGE_CELL_PX``(預設 512,判斷構圖 / 主體綽綽有餘),
四幀約 3–4× 省 token;格上燒錄 ``#N t.ts`` 標籤 + 前置 text block 附秒數對照表,
模型仍能精準對應「哪張圖是哪一秒」。單張圖片(照片)走 ``image_block`` 降到
``DIRECTOR_VIEW_RAW_DOWNSCALE_PX``(預設 768)。

重型相依(PIL / cv2)刻意延遲到函式內 import,使本模組在無這些套件的環境仍可被結構性載入。
"""
from __future__ import annotations

import base64
from io import BytesIO
from math import ceil

from config.director_config import (
    DIRECTOR_VIEW_RAW_DOWNSCALE_PX,
    DIRECTOR_VIEW_RAW_MONTAGE_CELL_PX,
)
import logging

logger = logging.getLogger(__name__)

# tool_result image block 的 JPEG MIME 與壓縮品質(control base64 大小 / token)
_JPEG_MEDIA_TYPE = "image/jpeg"
_JPEG_QUALITY = 85
# montage 版面:格間距(px)、標籤底色(半透明黑)與文字色、標籤字級相對格高的比例分母
_MONTAGE_GUTTER_PX = 4
_MONTAGE_BG_COLOR = (16, 16, 16)
_LABEL_BG_COLOR = (0, 0, 0)
_LABEL_TEXT_COLOR = (255, 255, 255)
_LABEL_FONT_DIVISOR = 12
_LABEL_MIN_FONT_PX = 14
_LABEL_PAD_PX = 3
# montage 超過此格數改 3 欄(2×2 之上的版面密度)
_MONTAGE_THREE_COL_THRESHOLD = 4
# 常見 Linux 粗體字型路徑(標籤燒錄用);缺字型時逐級退回 PIL 內建
_LABEL_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def text_block(text: str) -> dict:
    """組一個 text content block。"""
    return {"type": "text", "text": text}


def image_block(pil_image, downscale_px: int = DIRECTOR_VIEW_RAW_DOWNSCALE_PX) -> dict:
    """把 PIL Image 降解析、轉 JPEG base64,組成 image content block(單張圖片 / 照片用)。"""
    image = pil_image.copy()
    image.thumbnail((downscale_px, downscale_px))
    return _encoded_image_block(image)


def _encoded_image_block(image) -> dict:
    """把（已定尺寸的）PIL Image 轉 JPEG base64 image content block。"""
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    data = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": _JPEG_MEDIA_TYPE, "data": data},
    }


def grab_frames_at_times(abs_path: str, timestamps: list[float]) -> list[tuple[float, object]]:
    """
    一次開檔、依序 seek 抓多幀,回 ``[(秒數, RGB PIL Image), ...]``(抓不到的時間點跳過)。

    取代「每幀各開一次 VideoCapture」:同一支影片抓 4–6 幀時省去重複的容器解析 / 檔頭讀取。
    抓幀方式(POS_MSEC + read)與 ``video_frame_utils.grab_frame_at_time`` 對齊。
    """
    import cv2
    from PIL import Image

    from media_processor.pipeline.utils.video_frame_utils import cap_pil_resolution

    frames: list[tuple[float, object]] = []
    cap = cv2.VideoCapture(abs_path)
    try:
        for time_sec in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000)
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"[frame_blocks Warning] 抓幀失敗 (t={time_sec:.1f}s): {abs_path}")
                continue
            pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            frames.append((time_sec, cap_pil_resolution(pil_image)))
    finally:
        cap.release()
    return frames


def _load_label_font(size_px: int):
    """取標籤字型:優先 DejaVu 粗體 → PIL 內建可調字級 → 最終退回固定內建(合約:恆回可用字型)。"""
    from PIL import ImageFont

    try:
        return ImageFont.truetype(_LABEL_FONT_PATH, size_px)
    except OSError:
        pass
    try:
        return ImageFont.load_default(size=size_px)  # Pillow ≥ 10.1 支援指定字級
    except TypeError:
        return ImageFont.load_default()


def _draw_cell_label(cell, label_text: str) -> None:
    """在單格左上角燒錄 ``#N t.ts`` 標籤(半透明黑底白字),讓模型能對應格與秒數。"""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(cell)
    font_px = max(_LABEL_MIN_FONT_PX, cell.height // _LABEL_FONT_DIVISOR)
    font = _load_label_font(font_px)
    # textbbox 取實際文字外框,底色框比文字多留 padding
    left, top, right, bottom = draw.textbbox((_LABEL_PAD_PX, _LABEL_PAD_PX), label_text, font=font)
    draw.rectangle(
        (0, 0, right + _LABEL_PAD_PX, bottom + _LABEL_PAD_PX), fill=_LABEL_BG_COLOR
    )
    draw.text((_LABEL_PAD_PX, _LABEL_PAD_PX), label_text, fill=_LABEL_TEXT_COLOR, font=font)


def _build_montage(frames: list[tuple[float, object]], cell_px: int):
    """把多幀拼成一張網格 montage(每格長邊 ``cell_px``、左上燒錄 #N 秒數標籤),回 PIL Image。"""
    from PIL import Image

    cols = 2 if len(frames) <= _MONTAGE_THREE_COL_THRESHOLD else 3
    rows = ceil(len(frames) / cols)

    # 每格統一尺寸:取第一幀縮放後的大小(同支影片各幀同長寬比,直接對齊)
    cells = []
    for index, (time_sec, frame) in enumerate(frames):
        cell = frame.copy()
        cell.thumbnail((cell_px, cell_px))
        _draw_cell_label(cell, f"#{index + 1} {time_sec:.1f}s")
        cells.append(cell)
    cell_w = max(c.width for c in cells)
    cell_h = max(c.height for c in cells)

    canvas = Image.new(
        "RGB",
        (
            cols * cell_w + (cols - 1) * _MONTAGE_GUTTER_PX,
            rows * cell_h + (rows - 1) * _MONTAGE_GUTTER_PX,
        ),
        _MONTAGE_BG_COLOR,
    )
    for index, cell in enumerate(cells):
        col, row = index % cols, index // cols
        canvas.paste(cell, (col * (cell_w + _MONTAGE_GUTTER_PX), row * (cell_h + _MONTAGE_GUTTER_PX)))
    return canvas


def build_video_frame_blocks(
    abs_path: str,
    label: str,
    timestamps: list[float],
    cell_px: int = DIRECTOR_VIEW_RAW_MONTAGE_CELL_PX,
) -> list[dict]:
    """
    抓指定秒數的幀,組成 content blocks;全抓不到則拋。

    多幀拼成一張 montage(text 對照表 + 單一 image block),單幀直接一張圖(長邊 ``cell_px``,
    不用 768 全尺寸——單幀語意與 montage 格一致,維持 token 預算)。``label`` 為前綴標註
    (素材 id 或「範本」),讓模型知道這組畫面屬於誰。
    """
    frames = grab_frames_at_times(abs_path, timestamps)
    if not frames:
        raise RuntimeError("所有時間點都抓不到幀")

    if len(frames) == 1:
        time_sec, frame = frames[0]
        single = frame.copy()
        single.thumbnail((cell_px, cell_px))
        return [text_block(f"{label} @ {round(time_sec, 2)}s："), _encoded_image_block(single)]

    mapping = "、".join(f"#{i + 1}={t:.1f}s" for i, (t, _f) in enumerate(frames))
    return [
        text_block(f"{label} 拼格（各格左上有編號）：{mapping}"),
        _encoded_image_block(_build_montage(frames, cell_px)),
    ]


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
