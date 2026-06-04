"""素材處理器的抽象基底介面與共用視覺計算工具。"""

import cv2
import numpy as np
from abc import ABC, abstractmethod
from PIL import Image, ExifTags

from media_processor.models import SubjectBbox
from config.media_processor_config import (
    MOTION_STATIC_THRESHOLD, MOTION_DYNAMIC_THRESHOLD,
    COLOR_TEMP_THRESHOLD,
    CROP_PARTIAL_THRESHOLD, CROP_NOT_RECOMMENDED_THRESHOLD,
    DOMINANT_COLORS_K, DOMINANT_COLORS_RESIZE,
    KMEANS_ATTEMPTS, KMEANS_MAX_ITER, KMEANS_EPSILON,
    MOTION_SAMPLE_FRAMES,
)


class MediaStrategy(ABC):
    """
    策略模式 (Strategy)：定義所有素材處理器的標準介面。
    所有 Image/Video 處理器均繼承此類，並實作 process()。
    同時提供子類共用的視覺計算工具方法，消除重複邏輯。
    """

    @abstractmethod
    def process(self, file_path: str) -> dict:
        """執行素材感知分析，回傳標準格式的結果 dict。"""
        pass

    # ── Saliency Bbox ─────────────────────────────────────────────────────────

    @staticmethod
    def _compute_saliency_bbox(
        mask: np.ndarray, width: int, height: int
    ) -> SubjectBbox:
        """
        從顯著性遮罩計算主體必須保留的矩形區域（百分比座標）。
        取非零像素的 min/max x,y 作為 bbox；遮罩全黑時退回全畫面 (0,0,100,100)。
        """
        nonzero = cv2.findNonZero(mask)
        if nonzero is not None:
            x, y, w, h = cv2.boundingRect(nonzero)
            return SubjectBbox(
                x1=round(x / width * 100, 1),
                y1=round(y / height * 100, 1),
                x2=round((x + w) / width * 100, 1),
                y2=round((y + h) / height * 100, 1),
            )
        return SubjectBbox(x1=0.0, y1=0.0, x2=100.0, y2=100.0)

    @staticmethod
    def _union_bboxes(bboxes: list[SubjectBbox]) -> SubjectBbox:
        """多幀 SubjectBbox 取聯集，確保主體在整段影片中不被裁切。"""
        if not bboxes:
            return SubjectBbox(x1=0.0, y1=0.0, x2=100.0, y2=100.0)
        return SubjectBbox(
            x1=min(b.x1 for b in bboxes),
            y1=min(b.y1 for b in bboxes),
            x2=max(b.x2 for b in bboxes),
            y2=max(b.y2 for b in bboxes),
        )

    @staticmethod
    def _compute_crop_feasibility(bbox: SubjectBbox, aspect_ratio: float) -> str:
        """
        評估素材在 9:16 裁切下是否能保留主體。
        橫式素材（aspect_ratio > 1）的 bbox 寬度超過閾值時標記為 partial / not_recommended。
        直式素材預設 full（已是 9:16 格式）。
        """
        if aspect_ratio <= 1.0:
            return "full"
        bbox_width = bbox.x2 - bbox.x1
        if bbox_width > CROP_NOT_RECOMMENDED_THRESHOLD:
            return "not_recommended"
        if bbox_width > CROP_PARTIAL_THRESHOLD:
            return "partial"
        return "full"

    # ── 視覺特徵計算（cv2/PIL）────────────────────────────────────────────────

    @staticmethod
    def _compute_brightness(pil_image: Image.Image) -> float:
        """計算畫面平均亮度，正規化至 0–100。"""
        gray = np.array(pil_image.convert("L"))
        return round(float(gray.mean()) / 255.0 * 100, 1)

    @staticmethod
    def _compute_color_temperature(pil_image: Image.Image) -> str:
        """
        比較 R / B channel 均值判斷色調。
        R 明顯高於 B → warm；B 明顯高於 R → cool；否則 neutral。
        """
        arr = np.array(pil_image.convert("RGB"), dtype=np.float32)
        r_mean = arr[:, :, 0].mean()
        b_mean = arr[:, :, 2].mean()
        diff = r_mean - b_mean
        if diff > COLOR_TEMP_THRESHOLD:
            return "warm"
        if diff < -COLOR_TEMP_THRESHOLD:
            return "cool"
        return "neutral"

    @staticmethod
    def _compute_dominant_colors(
        pil_image: Image.Image, k: int = DOMINANT_COLORS_K
    ) -> list[str]:
        """
        K-means 取主色調，回傳 hex 字串列表（由佔比高至低排列）。縮小至 DOMINANT_COLORS_RESIZE 加速。

        以 ``cv2.kmeans`` 取代 ``sklearn.KMeans``：cv2 運算時釋放 GIL，且**不經 threadpoolctl 的
        ``dl_iterate_phdr`` 掃描共享庫**——後者首次呼叫會持有動態連結器鎖（``dl_load_write_lock``），
        與其他執行緒正在進行的原生擴充 ``dlopen`` 形成「GIL ↔ 連結器鎖」鎖序倒置而死結
        （與 ``SaliencyModelManager`` 改 CPU EP 同屬避免 GIL/連結器鎖卡死的修復）。
        """
        img = pil_image.convert("RGB").resize(
            (DOMINANT_COLORS_RESIZE, DOMINANT_COLORS_RESIZE)
        )
        # cv2.kmeans 要求 float32、(N, 3) 的連續陣列；每列為一個像素的 RGB 樣本
        arr = np.ascontiguousarray(np.array(img).reshape(-1, 3), dtype=np.float32)
        k = min(k, len(arr))
        # 收斂條件：達最大迭代次數「或」中心位移小於 epsilon（兩者擇一先滿足即停）
        criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
            KMEANS_MAX_ITER,
            KMEANS_EPSILON,
        )
        # KMEANS_PP_CENTERS：k-means++ 初始化（對應 sklearn 預設 init）；attempts 次取 compactness 最佳者
        _compactness, labels, centers = cv2.kmeans(
            arr, k, None, criteria, KMEANS_ATTEMPTS, cv2.KMEANS_PP_CENTERS
        )
        centers = centers.astype(int)
        # labels shape 為 (N, 1)，攤平後統計各群像素數作為主色佔比，降冪排序讓佔比高的色排前面
        counts = np.bincount(labels.flatten(), minlength=k)
        sorted_centers = centers[np.argsort(-counts)]
        return [f"#{int(c[0]):02x}{int(c[1]):02x}{int(c[2]):02x}" for c in sorted_centers]

    @staticmethod
    def _compute_motion_intensity(
        file_path: str, n_samples: int = MOTION_SAMPLE_FRAMES
    ) -> str:
        """
        取樣 n_samples 幀，計算相鄰幀差均值，分類為 static / moderate / dynamic。
        僅適用影片；圖片不呼叫此方法。
        """
        cap = cv2.VideoCapture(file_path)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count < 2:
            cap.release()
            return "static"

        indices = np.linspace(0, frame_count - 1, n_samples, dtype=int)
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ret, frame = cap.read()
            if ret:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        cap.release()

        if len(frames) < 2:
            return "static"

        diffs = [
            float(cv2.absdiff(frames[i], frames[i + 1]).mean())
            for i in range(len(frames) - 1)
        ]
        avg_diff = np.mean(diffs)

        if avg_diff < MOTION_STATIC_THRESHOLD:
            return "static"
        if avg_diff < MOTION_DYNAMIC_THRESHOLD:
            return "moderate"
        return "dynamic"

    # ── EXIF 元數據（圖片共用）────────────────────────────────────────────────

    @staticmethod
    def _extract_exif_metadata(pil_image: Image.Image) -> dict:
        """
        從 PIL 圖片解析 EXIF 元數據，提取拍攝時間與 GPS 座標。
        DateTimeOriginal 優先於 DateTime（後者可能為修改時間）。
        解析失敗時靜默回傳空字串，不影響主流程。
        """
        metadata = {"datetime": "", "gps_info": ""}
        try:
            exif = pil_image.getexif()
            if not exif:
                return metadata
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag == "DateTime":
                    metadata["datetime"] = str(value)
            exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            if exif_ifd:
                for tag_id, value in exif_ifd.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == "DateTimeOriginal":
                        metadata["datetime"] = str(value)
            gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if gps_ifd:
                gps_data = {
                    ExifTags.GPSTAGS.get(tag_id, tag_id): str(value)
                    for tag_id, value in gps_ifd.items()
                }
                if gps_data:
                    metadata["gps_info"] = str(gps_data)
        except Exception:
            pass
        return metadata
