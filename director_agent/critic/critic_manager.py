from director_agent.Critic.overlap_validator import OverlapValidator
from director_agent.Critic.duration_validator import DurationValidator

class CriticManager:
    """
    List-driven Chain of Responsibility (符合 Open/Closed 原則)。
    新增 Validator 只需在 validators 參數傳入，不須修改此類別本身。

    用法範例：
        CriticManager([OverlapValidator(), DurationValidator(), MyNewValidator()])
    """
    def __init__(self, validators=None):
        self.validators = validators or [OverlapValidator(), DurationValidator()]

    def validate_all(self, timeline_draft: list, compressed_assets: list) -> list:
        return [
            err
            for validator in self.validators
            for err in validator.validate(timeline_draft, compressed_assets)
        ]