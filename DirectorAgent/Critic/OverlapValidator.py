from DirectorAgent.Critic.BaseValidator import BaseValidator

class OverlapValidator(BaseValidator):
    def validate(self, timeline, assets):
        errors = []
        for i in range(len(timeline) - 1):
            curr_end = timeline[i].get("end_at")
            next_start = timeline[i+1].get("start_at")
            if curr_end is None:
                errors.append(f"Clip [{i}]: 缺少必要欄位 'end_at'")
                continue
            if next_start is None:
                errors.append(f"Clip [{i+1}]: 缺少必要欄位 'start_at'")
                continue
            if next_start < curr_end:
                errors.append(f"時間重疊：第 {i} 段結束於 {curr_end}，但第 {i+1} 段開始於 {next_start}")
        
        return errors