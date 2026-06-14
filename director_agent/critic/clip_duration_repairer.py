from config.director_config import SOURCE_END_OVERFLOW_REPAIR_TOLERANCE_SECONDS


class ClipDurationRepairer:
    """
    Deterministic 修補器:把導演藍圖中「source_end 微幅超出素材物理時長」的捨入溢位就地夾回。

    導演(LLM)常把 source_end 四捨五入到數位小數(例如把真實時長 1.6666666666666667s 寫成
    1.6667s),使其超出素材物理長度一個次毫秒的量。這純屬捨入雜訊——素材本就沒有那一格可放,
    夾回物理長度即可,毫無視覺影響。本修補器不依賴 LLM 反思重試:對每個影片片段,凡 source_end
    超出素材物理時長 (asset['dur']) 且溢位在容差內者,就地夾回 dur;溢位超過容差才視為導演真的
    要了不存在的片段,保留原值交由 Critic 如實標錯、退回重寫。設計上(與 :class:`ClipIdRepairer`
    同)置於 Critic 驗證『之前』,省下本可 deterministic 修掉的捨入溢位所觸發的反思往返;Critic
    仍負責真正大幅超界的最終把關。

    僅處理頂層 ``Clip.source_end``:子畫面 ``PipVideo`` 結構無 source_end 欄位,且 DurationValidator
    的物理邊界檢查亦只查頂層,範圍刻意對齊以免修補與驗證視角不一致。
    """

    # 影片片段才有物理擷取邊界;與 DurationValidator 同以此型別判斷是否做邊界檢查
    _VIDEO_TYPE = "video"

    def repair(self, timeline: list, assets: list) -> list[str]:
        """
        就地夾回 timeline 內微幅超界的 source_end,回傳人類可讀的修補紀錄清單。

        Args:
            timeline: 導演草稿的片段清單(dict);就地改寫其 source_end。
            assets: 壓縮後素材清單(每筆含 id / type / dur),作為物理時長查表來源。

        Returns:
            每筆「source_end 溢位 → 夾回」的修補說明字串;無任何修補回空清單。
        """
        # 建立 id → asset 快查表(與 DurationValidator 同以 a["id"] 為素材身分)
        asset_map = {a["id"]: a for a in assets if a.get("id")}

        repairs: list[str] = []
        for i, clip in enumerate(timeline):
            asset = asset_map.get(clip.get("clip_id"))
            # 素材查無(身分錯誤)交由 ClipIdRepairer / Critic 處理;非影片無物理擷取邊界,皆跳過
            if asset is None or asset.get("type") != self._VIDEO_TYPE:
                continue

            max_dur = asset.get("dur", 0)
            source_end = clip.get("source_end", 0)
            overflow = source_end - max_dur
            # 只夾回「正向且在容差內」的捨入溢位;非溢位不動、大幅超界保留原值留給 Critic 標錯
            if 0 < overflow <= SOURCE_END_OVERFLOW_REPAIR_TOLERANCE_SECONDS:
                clip["source_end"] = max_dur
                repairs.append(
                    f"Clip [{i}] ({clip.get('clip_id')}): source_end {source_end}s → {max_dur}s "
                    f"(超界 {overflow:.6f}s,捨入溢位夾回物理時長)"
                )
        return repairs
