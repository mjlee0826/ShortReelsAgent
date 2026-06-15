"""
Director provider 工廠 (Factory Pattern)：回傳 Phase 4 導演 agentic loop 用的 model manager。

Phase 4 改造為 Claude agentic tool-use loop（需 ``ClaudeModelManager.stream_director_turn`` 的串流多輪
能力，Gemini 無對應介面），故 clean cutover 後一律回 Claude；保留本工廠是維持「呼叫端零分支」的接縫，
日後若有第二家串流導演實作，於此切換即可。子模組 import 延遲到函式內，沿用不 eager 載入 SDK 的慣例。
"""
from model.infra.base_model_manager import BaseModelManager


def get_director_manager() -> BaseModelManager:
    """回傳 director agentic loop 用的 model manager（Claude）。"""
    from model.managers.claude_model_manager import ClaudeModelManager
    return ClaudeModelManager()
