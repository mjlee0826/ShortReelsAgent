from config.media_processor_config import (
    AESTHETIC_SCORE_REJECT_THRESHOLD,
    TECHNICAL_SCORE_REJECT_THRESHOLD,
)

# 缺臉資訊時的空 dict 預設(避免 None.get)
_EMPTY_FACES: dict = {}
# bbox 缺值時的全幅預設(導演計算 object_position 的保底基準)
_DEFAULT_BBOX = {"x1": 0, "y1": 0, "x2": 100, "y2": 100}
# 美學分缺值時回給導演的中性預設(0~100 分制)
_DEFAULT_AES_SCORE = 60.0


class ContextCompressor:
    """
    Strategy Pattern: 負責素材的特徵降維與「非破壞性」防禦過濾。

    評分與過濾已解耦:tech / aes 一律由 Phase 1 算好寫進 metadata(現含 Complex)。本層只做寬容的
    最終把關 —— 唯有「技術分極低」AND「美學分也低」雙重條件同時成立才剔除,避免 MUSIQ 對動態模糊 /
    低光素材的單訊號低估造成好素材被誤刪;缺任一分數的舊快取一律放行。導演端仍拿得到原始分數自行取捨。
    """

    def compress(self, raw_assets: list) -> list:
        """逐素材做寬容雙訊號過濾 + 特徵降維,回傳給導演的精簡清單。"""
        compressed_list = []

        for asset in raw_assets:
            metadata = asset.get("metadata", {})

            # --- 1. 寬容雙訊號過濾(非破壞性:不刪檔,只是不送進導演決策)---
            if self._is_low_quality(metadata):
                print(f"[Compressor] 剔除技術+美學雙低素材: {asset.get('file')}")
                continue

            # --- 2. 特徵降維 (Dimensionality Reduction) ---
            # 以 bbox 中心點（(x1+x2)/2, (y1+y2)/2）提供導演計算 object_position 的基準
            raw_bbox = metadata.get("subject_bbox", _DEFAULT_BBOX)
            faces = metadata.get("faces") or _EMPTY_FACES

            base_info = {
                # 素材 id = relpath 身分(如 raw/photo.jpg);與 blueprint clip_id、/static URL 片段一致
                "id": asset.get("file"),
                "type": asset.get("type"),
                "res": {"w": metadata.get("width"), "h": metadata.get("height")},
                "aes": metadata.get("aesthetic_score", _DEFAULT_AES_SCORE),
                "cap": metadata.get("caption", ""),
                # bbox：導演計算 object_position 的依據（取代舊的 focus 單點）
                "bbox": raw_bbox,
                "crop": metadata.get("crop_feasibility", "full"),
                # 視覺語意標籤
                "mood": metadata.get("mood", ""),
                "scene_tags": metadata.get("scene_tags", []),
                "cam": metadata.get("camera_angle", ""),
                "actions": metadata.get("action_tags", []),
                "tod": metadata.get("time_of_day", ""),
                # 視覺特徵
                "bright": metadata.get("brightness", 0.0),
                "colors": metadata.get("dominant_colors", []),
                # 拍攝時間與地點（圖片來自 EXIF、影片來自容器標籤）
                "time": metadata.get("creation_time", ""),
                "geo": metadata.get("location_gps", ""),
            }

            # 臉部資訊（有臉時補充）
            if faces.get("has_faces"):
                base_info["face_count"] = faces.get("face_count", 0)

            # 根據素材類型補強影片特有資訊
            if asset.get("type") == "video":
                base_info["dur"] = metadata.get("duration", 0)
                base_info["fps"] = metadata.get("fps", 30.0)
                base_info["motion"] = metadata.get("motion_intensity", "")
                base_info["has_speech"] = metadata.get("has_speech", False)
                base_info["lang"] = metadata.get("spoken_language", "")
                base_info["cuts"] = metadata.get("scene_cuts", [])

                # 若為一般影片，濃縮聲音描述
                if not metadata.get("is_dense_indexed"):
                    base_info["audio"] = {
                        "vocal": metadata.get("audio_transcript", {}).get("text", ""),
                        "env": metadata.get("environmental_sounds", "")
                    }
                # 若為 Complex 影片，僅保留事件索引
                else:
                    base_info["is_complex"] = True
                    base_info["events"] = metadata.get("multimodal_event_index", [])

            compressed_list.append(base_info)

        return compressed_list

    @staticmethod
    def _is_low_quality(metadata: dict) -> bool:
        """
        技術分與美學分「雙雙偏低」才判定為低品質而剔除(寬容把關)。

        任一分數缺值(如無分數的舊 Complex 快取)即放行,絕不因單一訊號低估誤刪;
        兩者皆存在且同時低於各自門檻,才視為「壞幀 + 構圖也差」的真低品質素材。
        """
        tech_score = metadata.get("technical_score")
        aes_score = metadata.get("aesthetic_score")
        if tech_score is None or aes_score is None:
            return False
        return (
            tech_score < TECHNICAL_SCORE_REJECT_THRESHOLD
            and aes_score < AESTHETIC_SCORE_REJECT_THRESHOLD
        )
