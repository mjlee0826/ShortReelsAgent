from config.media_processor_config import (
    AESTHETIC_SCORE_REJECT_THRESHOLD,
    TECHNICAL_SCORE_REJECT_THRESHOLD,
)
from prompt_manager.schemas import CastingCard

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
            # top-N 候選主體（含 label/信心/各自 bbox）：bbox 為系統自動選定的最佳框，
            # subjects 提供替代主體讓導演按使用者意圖／情緒改選（mode A 誤選主體的補救）
            subjects = self._compress_subjects(metadata.get("subject_candidates", []))
            faces = metadata.get("faces") or _EMPTY_FACES

            base_info = {
                # 素材 id = relpath 身分(如 raw/photo.jpg);與 blueprint clip_id、/static URL 片段一致
                "id": asset.get("file"),
                "type": asset.get("type"),
                "res": {"w": metadata.get("width"), "h": metadata.get("height")},
                "aes": metadata.get("aesthetic_score", _DEFAULT_AES_SCORE),
                # 技術畫質分（供導演自行取捨；過濾閘只剔雙低，分數仍完整給導演）
                "tech": metadata.get("technical_score"),
                "cap": metadata.get("caption", ""),
                # 攝影評論（鏡頭語言 / 情緒氛圍的深度描述）
                "critique": metadata.get("cinematic_critique", ""),
                # bbox：導演計算 object_position 的依據（系統自動選定的最佳主體框）
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
                "color_temp": metadata.get("color_temperature", ""),  # warm / cool / neutral
                "colors": metadata.get("dominant_colors", []),
                # 拍攝時間與地點（圖片來自 EXIF、影片來自容器標籤）
                "time": metadata.get("creation_time", ""),
                "geo": metadata.get("location_gps", ""),
            }

            # 候選主體清單（≥1 個就帶：保留主體的 label / 信心，連單一主體的語意標籤也不丟）
            if subjects:
                base_info["subjects"] = subjects

            # 臉部資訊（有臉時補充數量與最大臉佔比，後者暗示特寫程度）
            if faces.get("has_faces"):
                base_info["face_count"] = faces.get("face_count", 0)
                base_info["face_ratio"] = faces.get("largest_face_ratio", 0.0)

            # 根據素材類型補強影片特有資訊
            if asset.get("type") == "video":
                base_info["dur"] = metadata.get("duration", 0)
                base_info["fps"] = metadata.get("fps", 30.0)
                base_info["motion"] = metadata.get("motion_intensity", "")
                base_info["has_speech"] = metadata.get("has_speech", False)
                base_info["lang"] = metadata.get("spoken_language", "")
                base_info["cuts"] = metadata.get("scene_cuts", [])

                # 完整逐字稿(text + 帶時間戳 chunks + language)一律給導演（simple/complex 皆送），
                # 讓導演用 chunks 的 timestamp 精準卡 text_overlays 字幕與 bgm_volume ducking
                base_info["audio"] = {
                    "transcript": metadata.get("audio_transcript", {}),
                    "env": metadata.get("environmental_sounds", []),
                }
                # Complex 影片額外保留逐段視聽事件索引
                if metadata.get("is_dense_indexed"):
                    base_info["is_complex"] = True
                    base_info["events"] = metadata.get("multimodal_event_index", [])

            compressed_list.append(base_info)

        return compressed_list

    def to_casting_cards(self, compressed_assets: list) -> list:
        """
        把完整 dossier 清單投影成第一段 Casting 用的精簡卡片（:class:`CastingCard`）。

        只保留支撐『選材 / 排序 / 粗略時長』的欄位；逐句時間戳 chunks、完整事件索引、bbox、主體
        候選、攝影評論、色彩 / 亮度等「精修才需要」的重料一律不投影（第二段再按 id 取完整 dossier），
        這正是兩階段縮小 context 的關鍵。影片才有的 dur/motion/has_speech/transcript_text/event_digest
        缺值留 None，卡片經 ``model_dump(exclude_none=True)`` 後自動精簡。
        """
        cards = []
        for dossier in compressed_assets:
            asset_id = dossier.get("id")
            if not asset_id:
                continue  # 無身分的素材無法被選回，跳過

            card = CastingCard(
                id=asset_id,
                type=dossier.get("type", ""),
                aes=dossier.get("aes", 0.0),
                tech=dossier.get("tech"),
                cap=dossier.get("cap", ""),
                mood=dossier.get("mood", ""),
                scene_tags=dossier.get("scene_tags", []),
                actions=dossier.get("actions", []),
                crop=dossier.get("crop", "full"),
                time=dossier.get("time", ""),
                geo=dossier.get("geo", ""),
            )

            # 影片專屬：時長 / 動態 / 語音旗標 + 逐字稿全文（無時間戳）+ 事件視覺摘要
            if dossier.get("type") == "video":
                card.dur = dossier.get("dur")
                card.motion = dossier.get("motion")
                card.has_speech = dossier.get("has_speech")
                # 逐字稿只取純文字 text，帶時間戳的 chunks 留待第二段精修對齊字幕 / ducking
                transcript = (dossier.get("audio") or {}).get("transcript") or {}
                if transcript.get("text"):
                    card.transcript_text = transcript["text"]
                # 事件索引只抽各段 visual_layer（畫面動作摘要），丟棄時間戳 / audio_layer / 主體框
                events = dossier.get("events") or []
                digest = [e.get("visual_layer", "") for e in events if e.get("visual_layer")]
                if digest:
                    card.event_digest = digest

            cards.append(card)
        return cards

    @staticmethod
    def _compress_subjects(candidates: list) -> list:
        """
        把 metadata 的 subject_candidates 降維成導演可讀的精簡候選清單。

        只保留 label / 信心 / bbox(導演據 bbox 中心改算 object_position),已依信心遞減排序。
        缺值給安全預設,確保送進導演的 JSON 結構穩定。
        """
        compact = []
        for candidate in candidates:
            compact.append(
                {
                    "label": candidate.get("label", ""),
                    "conf": candidate.get("confidence", 0.0),
                    "bbox": candidate.get("bbox", _DEFAULT_BBOX),
                }
            )
        return compact

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
