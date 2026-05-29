import os

from config.media_processor_config import (
    TECHNICAL_SCORE_FILTER_THRESHOLD,
    TECHNICAL_SCORE_FORCE_PASS,
)


class ContextCompressor:
    """
    Strategy Pattern: 負責素材的特徵降維與防禦性過濾。
    實作「寬容過濾邏輯」：確保 ComplexVideo 不會因為缺乏技術分數而被誤刪。
    """
    def compress(self, raw_assets: list) -> list:
        compressed_list = []

        for asset in raw_assets:
            metadata = asset.get("metadata", {})

            # --- 1. 防禦性快篩 ---
            # ComplexVideo 無 technical_score，給予 TECHNICAL_SCORE_FORCE_PASS 強制放行
            tech_score = metadata.get("technical_score")
            if tech_score is None:
                tech_score = TECHNICAL_SCORE_FORCE_PASS

            if tech_score < TECHNICAL_SCORE_FILTER_THRESHOLD:
                print(f"[Compressor] 剔除畫質過低素材: {asset.get('file')}")
                continue

            # --- 2. 特徵降維 (Dimensionality Reduction) ---
            # 以 bbox 中心點（(x1+x2)/2, (y1+y2)/2）提供導演計算 object_position 的基準
            raw_bbox = metadata.get("subject_bbox", {"x1": 0, "y1": 0, "x2": 100, "y2": 100})
            faces = metadata.get("faces") or {}

            base_info = {
                "id": os.path.basename(asset.get("file")),
                "type": asset.get("type"),
                "res": {"w": metadata.get("width"), "h": metadata.get("height")},
                "aes": metadata.get("aesthetic_score", 60.0),
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
