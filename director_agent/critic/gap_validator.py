from director_agent.critic.base_validator import BaseValidator

# 相鄰片段允許的最大時間間隙(秒)：超過視為黑縫。與 DurationValidator 的時長容差同量級，
# 容許 round 至幀的微小誤差，但擋掉真正的空隙。
GAP_TOLERANCE_SECONDS = 0.1


class GapValidator(BaseValidator):
    """
    責任鏈模式：時間軸連續性驗證器。

    前端 Remotion 以「邊界幀差」算片段長度，要求相鄰片段首尾相接（end_at[i] == start_at[i+1]），
    否則中間會出現黑幀閃爍。``OverlapValidator`` 已擋重疊（next_start < curr_end），本驗證器補擋
    反向問題——正向間隙（next_start 明顯大於 curr_end）；兩者合計確保時間軸嚴格無縫。
    """

    def validate(self, timeline: list, assets: list) -> list:
        """檢查相鄰片段是否存在超過容差的時間間隙(黑縫)。"""
        errors = []
        for i in range(len(timeline) - 1):
            curr_end = timeline[i].get("end_at")
            next_start = timeline[i + 1].get("start_at")
            # 缺欄位交由 OverlapValidator 回報；此處只在兩者皆有值時檢查間隙
            if curr_end is None or next_start is None:
                continue
            gap = next_start - curr_end
            if gap > GAP_TOLERANCE_SECONDS:
                errors.append(
                    f"時間間隙：第 {i} 段結束於 {curr_end}，第 {i+1} 段才於 {next_start} 開始"
                    f"（間隙 {gap:.2f}s，會造成黑幀閃爍；相鄰片段須首尾相接）"
                )
        return errors
