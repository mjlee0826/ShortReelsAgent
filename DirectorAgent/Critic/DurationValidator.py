from DirectorAgent.Critic.BaseValidator import BaseValidator

class DurationValidator(BaseValidator):
    """
    責任鏈模式：長度合法性驗證器。
    檢查點：
    1. 影片素材的 source_end 是否超過了原始檔案的物理總時長。
    2. 片段的播放長度 (end_at - start_at) 是否大於 0。
    """
    def validate(self, timeline, assets):
        errors = []
        # 建立一個快速查詢表，加速驗證過程
        asset_map = {a["id"]: a for a in assets}

        for i, clip in enumerate(timeline):
            clip_id = clip.get("clip_id")
            
            # 1. 檢查 ID 是否存在
            if clip_id not in asset_map:
                errors.append(f"Clip [{i}]: 使用了不存在的素材 ID '{clip_id}'")
                continue
                
            asset = asset_map[clip_id]
            target_duration = clip.get("end_at", 0) - clip.get("start_at", 0)
            
            # 2. 檢查時長是否為正數
            if target_duration <= 0:
                errors.append(f"Clip [{i}] ({clip_id}): 播放時長必須大於 0 (目前為 {target_duration}s)")

            # 3. 針對影片進行物理邊界檢查
            if asset["type"] == "video":
                source_start = clip.get("source_start", 0)
                source_end = clip.get("source_end", 0)
                max_dur = asset.get("dur", 0)
                
                if source_end > max_dur:
                    errors.append(
                        f"Clip [{i}] ({clip_id}): 安排的結束時間 ({source_end}s) "
                        f"超過了素材原始長度 ({max_dur}s)"
                    )
                
                if (source_end - source_start) <= 0:
                    errors.append(f"Clip [{i}] ({clip_id}): 影片裁剪區間無效")

        # 若還有下一關，繼續往下送審
        if self.next:
            return errors + self.next.validate(timeline, assets)
        return errors