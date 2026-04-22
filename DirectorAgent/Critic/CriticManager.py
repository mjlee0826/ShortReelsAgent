from DirectorAgent.Critic.OverlapValidator import OverlapValidator
from DirectorAgent.Critic.DurationValidator import DurationValidator

class CriticManager:
    """
    Chain of Responsibility (責任鏈模式) 的管理者。
    負責將草稿依序送入各個冷酷無情的邏輯驗證器中。
    """
    def __init__(self):
        # 建立驗證器鏈條：OverlapValidator -> (未來可擴充 DurationValidator) -> None
        # 這裡示範掛載單一驗證器，未來可輕易鏈接：
        # self.chain_head = OverlapValidator(DurationValidator(None))
        self.chain_head = OverlapValidator(DurationValidator(None))

    def validate_all(self, timeline_draft: list, compressed_assets: list) -> list:
        """
        執行所有驗證邏輯，並收集所有錯誤訊息。
        """
        if not self.chain_head:
            return []
            
        # 啟動責任鏈驗證
        errors = self.chain_head.validate(timeline_draft, compressed_assets)
        return errors