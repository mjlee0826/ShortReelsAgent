"""
video_frame_utils:影片 Stage 共用的 cv2 取幀 / metadata 輔助函式 (Utility / DRY)。

把「用 cv2 開影片抓 metadata」「抓指定秒數的幀」「在指定秒數算主體 bbox」這幾段會被多個影片 Stage
重複用到的 cv2 boilerplate 集中於此(DecodeVideo 取 metadata+代表幀、SaliencyUnion 三幀、EventBbox
逐 event 都要「取幀→saliency→有臉覆蓋」)。引擎(saliency / mediapipe)以參數注入(依賴注入),
保持本模組對 model 層無耦合。

邏輯與原 ``AbstractVideoProcessor`` 的 ``_extract_video_metadata`` / ``_extract_middle_frame_pil`` /
``_get_saliency_at_time`` 逐字對齊,確保輸出與 legacy 一致。
"""
from __future__ import annotations

from typing import Optional

import cv2
from PIL import Image

from media_processor.media_strategy import MediaStrategy
from media_processor.models import SubjectBbox
from media_tools.ffmpeg_adapter import FFmpegAdapter

# metadata 數值四捨五入位數(逐字對齊原 _extract_video_metadata)
_ASPECT_RATIO_NDIGITS = 4
_FPS_NDIGITS = 2
# 抓幀失敗 / 無顯著區域時退回的全畫面安全區 (x1,y1,x2,y2)
_FULL_FRAME_BBOX = (0.0, 0.0, 100.0, 100.0)


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
            return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except Exception as e:
        # 抓幀失敗不致命(下游退預設 / 安全區),印警告協助定位
        print(f"[VideoFrameUtils Warning] 抓幀失敗 (t={time_sec:.1f}s): {e}")
    return None


def compute_saliency_bbox_at_time(
    file_path: str,
    time_sec: float,
    saliency_engine,
    mediapipe_engine,
) -> SubjectBbox:
    """
    在影片指定時間點計算主體 bbox(逐字對齊原 ``_get_saliency_at_time``)。

    流程:抓幀 → U2-Net saliency mask → 換算百分比 bbox;若偵測到臉,以臉部 bbox 覆蓋(語意更準確)。
    任一步失敗(抓幀 / 推論)都退回全畫面安全區 (0,0,100,100)。引擎由呼叫端(Stage)注入,以利共用與測試。
    """
    try:
        pil_image = grab_frame_at_time(file_path, time_sec)
        if pil_image is not None:
            width, height = pil_image.size
            mask = saliency_engine.get_saliency_mask(pil_image)
            bbox = MediaStrategy._compute_saliency_bbox(mask, width, height)
            # 臉部偵測:有臉則以 face bbox 覆蓋(語意更準確)
            _, face_bbox = mediapipe_engine.detect(pil_image)
            if face_bbox is not None:
                bbox = face_bbox
            return bbox
    except Exception as e:
        # 推論失敗退回全畫面安全區;印警告(saliency 本身另有內部 log)
        print(f"[VideoFrameUtils Warning] saliency 計算失敗 (t={time_sec:.1f}s): {e}")
    x1, y1, x2, y2 = _FULL_FRAME_BBOX
    return SubjectBbox(x1=x1, y1=y1, x2=x2, y2=y2)
