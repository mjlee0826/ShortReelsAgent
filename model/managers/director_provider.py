"""
Director provider 工廠 (Factory Pattern)：依環境變數回傳 Phase 4 導演藍圖要用的 model manager。

讓「導演大腦」能在 Claude（預設）與 Gemini 之間切換做 A/B，呼叫端（``SchedulingState``）零分支。
兩個 manager 都 duck-type 出 ``.prompt_manager`` 與 ``.generate_director_plan(prompt, schema)``，
故回傳型別統一標註為基底 ``BaseModelManager``。子模組 import 刻意延遲到分支內，沿用
``model/managers/__init__.py`` 不 eager re-export 的延遲載入慣例（避免一次拖入兩家 SDK）。
"""
from config.model_config import DIRECTOR_PROVIDER, DIRECTOR_PROVIDER_GEMINI
from model.infra.base_model_manager import BaseModelManager


def get_director_manager() -> BaseModelManager:
    """依 ``DIRECTOR_PROVIDER`` 回傳 director 用的 model manager（預設 Claude）。"""
    if DIRECTOR_PROVIDER == DIRECTOR_PROVIDER_GEMINI:
        from model.managers.gemini_model_manager import GeminiModelManager
        return GeminiModelManager()
    # 預設（claude，或任何未知值）一律走 Claude
    from model.managers.claude_model_manager import ClaudeModelManager
    return ClaudeModelManager()
