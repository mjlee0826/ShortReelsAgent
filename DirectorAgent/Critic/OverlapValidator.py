from DirectorAgent.Critic.BaseValidator import BaseValidator

class OverlapValidator(BaseValidator):
    def validate(self, timeline, assets):
        errors = []
        for i in range(len(timeline) - 1):
            curr_end = timeline[i]["end_at"]
            next_start = timeline[i+1]["start_at"]
            if next_start < curr_end:
                errors.append(f"時間重疊：第 {i} 段結束於 {curr_end}，但第 {i+1} 段開始於 {next_start}")
        
        if self.next:
            return errors + self.next.validate(timeline, assets)
        return errors