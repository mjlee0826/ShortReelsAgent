from director_agent.critic.overlap_validator import OverlapValidator
from director_agent.critic.duration_validator import DurationValidator
from director_agent.critic.gap_validator import GapValidator

class CriticManager:
    """
    List-driven Chain of Responsibility (符合 Open/Closed 原則)。
    新增 Validator 只需在 validators 參數傳入，不須修改此類別本身。

    預設責任鏈：重疊(Overlap) + 長度/物理邊界(Duration) + 連續性無縫(Gap)；
    track_id 由後端依配樂 DNA 注入，故不納入驗證。

    用法範例：
        CriticManager([OverlapValidator(), DurationValidator(), MyNewValidator()])
    """
    def __init__(self, validators=None):
        self.validators = validators or [OverlapValidator(), DurationValidator(), GapValidator()]

    def validate_all(self, timeline_draft: list, compressed_assets: list) -> list:
        return [
            err
            for validator in self.validators
            for err in validator.validate(timeline_draft, compressed_assets)
        ]