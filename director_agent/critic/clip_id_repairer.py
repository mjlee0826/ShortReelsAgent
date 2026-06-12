import os

from config.app_config import STANDARDIZED_MARKER


class ClipIdRepairer:
    """
    Deterministic 修補器:把導演藍圖中「對不上素材庫」的 clip_id 以 basename stem 反查自動校正。

    導演(LLM)偶爾會把 standardized/xxx_std.mp4 這類身分「正規化」成 raw/xxx.mp4(去前綴 / 去 _std),
    產出素材庫不存在的 clip_id。本修補器不依賴 LLM 反思重試:對每個無效 clip_id,去掉資料夾與副檔名、
    再剝掉 _std 標記取得 stem,反查素材庫中該 stem「唯一對應」的合法 id 並就地改寫。stem 查無或多義
    (多筆同 stem)才保留原值,交由 Critic 如實標錯。設計上置於 Critic 驗證『之前』,省下本可 deterministic
    修掉的身分錯誤(raw/standardized 混淆)所觸發的反思往返;Critic 仍負責真正查無 / 多義的最終把關。
    """

    def repair(self, timeline: list, assets: list) -> list[str]:
        """
        就地校正 timeline 內無效的 clip_id(含巢狀 pip_video),回傳人類可讀的修補紀錄清單。

        Args:
            timeline: 導演草稿的片段清單(dict);就地改寫其 clip_id / pip_video.clip_id。
            assets: 壓縮後素材清單(每筆含 id),作為合法身分集合與 stem 反查表的來源。

        Returns:
            每筆「原 id → 新 id」的修補說明字串;無任何修補回空清單。
        """
        # 合法身分集合 + stem → {合法 id} 反查表(與 DurationValidator 同以 a["id"] 為素材身分)
        valid_ids = {a["id"] for a in assets if a.get("id")}
        stem_index = self._build_stem_index(valid_ids)

        repairs: list[str] = []
        for i, clip in enumerate(timeline):
            # 主片段 clip_id
            fixed = self._resolve(clip.get("clip_id"), valid_ids, stem_index)
            if fixed is not None:
                repairs.append(f"Clip [{i}]: clip_id '{clip.get('clip_id')}' → '{fixed}'")
                clip["clip_id"] = fixed
            # 畫中畫 pip_video.clip_id(巢狀,存在且為 dict 才嘗試修)
            pip = clip.get("pip_video")
            if isinstance(pip, dict):
                fixed_pip = self._resolve(pip.get("clip_id"), valid_ids, stem_index)
                if fixed_pip is not None:
                    repairs.append(
                        f"Clip [{i}].pip_video: clip_id '{pip.get('clip_id')}' → '{fixed_pip}'"
                    )
                    pip["clip_id"] = fixed_pip
        return repairs

    @staticmethod
    def _resolve(clip_id, valid_ids: set, stem_index: dict) -> str | None:
        """回傳該 clip_id 應改寫成的合法 id;已合法 / 空值 / 無法唯一反查時回 None(不需 / 不可修)。"""
        # 空值或本就合法:不動
        if not clip_id or clip_id in valid_ids:
            return None
        candidates = stem_index.get(ClipIdRepairer._normalize_stem(clip_id))
        # 唯一對應才 deterministic 校正;查無或多義(同 stem 多筆)交由 Critic 標錯
        if candidates and len(candidates) == 1:
            return next(iter(candidates))
        return None

    @staticmethod
    def _build_stem_index(valid_ids: set) -> dict:
        """建立 stem → {合法 id} 反查表(同 stem 多筆即視為多義,不參與自動校正)。"""
        index: dict[str, set[str]] = {}
        for asset_id in valid_ids:
            index.setdefault(ClipIdRepairer._normalize_stem(asset_id), set()).add(asset_id)
        return index

    @staticmethod
    def _normalize_stem(asset_id: str) -> str:
        """
        取素材身分的正規化 stem:去資料夾與副檔名後,再剝掉尾端 _std 標記。

        如此 raw/clip.jpg、standardized/clip_std.mp4、被 LLM 寫錯的 raw/clip_std.mp4 皆正規化成同一
        stem「clip」,使 raw/standardized 分層與 _std 後綴的差異不影響反查(忽略資料夾與標準化標記)。
        """
        stem = os.path.splitext(os.path.basename(asset_id))[0]
        if stem.endswith(STANDARDIZED_MARKER):
            stem = stem[: -len(STANDARDIZED_MARKER)]
        return stem
