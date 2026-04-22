from DirectorAgent.States.BaseState import BaseState
from DirectorAgent.Critic.CriticManager import CriticManager

class ReflectionState(BaseState):
    """
    狀態：自我反思與糾錯 (Self-Reflection)。
    將草稿送交 Critic 審查。若有錯，產生 Error Prompt 並退回前一狀態重寫；
    若無錯或達到重試上限，則結束流程。
    """
    def __init__(self):
        # 實例化審查委員會 (包含所有實作的 Validator)
        self.critic = CriticManager()
        # 設定最大迭代次數，避免 API 無限扣款
        self.max_retries = 3

    def run(self, context: dict):
        print("\n[Agent State] 進入 ReflectionState：正在進行 Critic 嚴格驗證...")
        
        draft = context.get("timeline_draft", [])
        assets = context.get("assets", [])
        
        # 初始化重試計數器
        if "retry_count" not in context:
            context["retry_count"] = 0

        # 防呆機制：如果 LLM 徹底壞掉連 JSON 都沒吐出來
        if not draft:
            errors = ["嚴重錯誤：未能生成有效的 JSON 時間軸陣列。"]
        else:
            # 呼叫責任鏈進行物理與邏輯驗證
            errors = self.critic.validate_all(draft, assets)

        # 情境 A：完美通過驗證！
        if not errors:
            print("✅ [Critic] 驗證通過！時間軸邏輯完美無瑕。")
            context["final_timeline"] = draft
            return None  # 回傳 None 代表狀態機終止 (流程結束)

        # 情境 B：發現錯誤，準備退回重寫
        context["retry_count"] += 1
        print(f"❌ [Critic] 發現 {len(errors)} 個錯誤 (第 {context['retry_count']} 次糾錯)")
        for err in errors:
            print(f"   - {err}")

        # 如果超過最大重試次數，為了系統穩定性，強制結束並拋出例外 (或妥協輸出)
        if context["retry_count"] >= self.max_retries:
            print("🚨 [Agent State] 達到最大糾錯次數！將強行輸出目前版本。")
            context["final_timeline"] = draft
            return None

        # 整理錯誤訊息，塞回 context 供 SchedulingState 反思
        context["error_prompt"] = "\n".join([f"- {err}" for err in errors])
        
        # 狀態切換：打回重構！
        from DirectorAgent.States.SchedulingState import SchedulingState
        return SchedulingState()