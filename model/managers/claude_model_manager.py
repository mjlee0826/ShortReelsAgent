"""
ClaudeModelManager：雲端導演大腦 (Claude)，透過 Anthropic SDK 完成 Phase 4 導演藍圖的
結構化 + agentic 推理。與 ``GeminiModelManager`` 平行，專責 director blueprint 這條接縫。

設計模式
--------
- **Template Method**：繼承 ``BaseModelManager``，Singleton 與鎖序由基底提供；
  子類只需實作 ``_initialize`` 與業務方法 ``generate_director_plan``。
- **Strategy**：``PromptManager`` 可由外部注入（``set_prompt_manager``），與 Gemini 對稱。
- **Adapter**：把 Anthropic 的 usage 物件交由 ``record_anthropic_usage`` 轉成共同成本帳本記錄。

結構化輸出策略
--------------
``schema`` 非 None 時走 Anthropic structured outputs（``messages.parse(output_format=...)``），
由 SDK 保證輸出結構與 enum 合法，並自動處理 pydantic 不被 server 支援的數值界線
（``ge``/``le`` → client 端驗證）。回傳已驗證的 ``parsed_output``，再 ``model_dump_json()``
轉回 JSON 字串，維持與 ``GeminiModelManager`` 相同的「回傳 str、下游 ``json.loads``」契約。

GPU 策略
--------
雲端 API 模型不佔本地 GPU；未設 ``self.device`` → ``_uses_gpu()`` 自動回 False，
forward 跳過 L2 GpuGate 與 ModelPool VRAM 重檢（與 Gemini 同路，不進 warmup / 資源池）。
"""
import os

import anthropic
from pydantic import BaseModel

from config.model_config import CLAUDE_DIRECTOR_MAX_TOKENS, CLAUDE_DIRECTOR_MODEL
from model.infra.base_model_manager import BaseModelManager, synchronized_inference
from model.infra.usage_ledger import phase_for_mode, record_anthropic_usage
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.task_mode import TaskMode

# adaptive thinking：導演藍圖屬複雜 agentic 推理，讓 Claude 自行決定思考深度。
# Opus 4.x 僅支援 adaptive（用 budget_tokens 會 400）；effort 省略 = 預設 high。
_ADAPTIVE_THINKING = {"type": "adaptive"}


class ClaudeModelManager(BaseModelManager):
    """雲端導演大腦 (Claude)：Phase 4 導演藍圖的結構化 + agentic 推理。"""

    # 雲端 API 無 VRAM / 執行緒安全問題，client 可並發；不以 L3 鎖序列化推論
    # （同 GeminiModelManager；序列化只會把吞吐壓成 1）。並發度交由 API 資源池控制。
    SERIALIZE_INFERENCE = False

    def _initialize(self, device_id: int = 0):
        """初始化 Anthropic Client。device_id 對雲端 API 無效，保留簽名一致性。"""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("嚴重錯誤：找不到 ANTHROPIC_API_KEY 環境變數！請設定後再執行。")

        self.client = anthropic.Anthropic(api_key=api_key)
        # 持有 prompt_manager 供呼叫端 manager.prompt_manager 取用（與 Gemini 對稱）
        self.prompt_manager = DefaultPromptManager()

    def set_prompt_manager(self, prompt_manager: BasePromptManager):
        """替換 Prompt Manager（Strategy Pattern），與 Gemini 對稱。"""
        self.prompt_manager = prompt_manager

    def _record(self, response, model: str) -> None:
        """把本次呼叫的 token 用量記入當前成本帳本（無帳本則 no-op）；phase 固定為 Phase 4。"""
        phase = phase_for_mode(TaskMode.DIRECTOR_BLUEPRINT)
        if phase is not None:
            record_anthropic_usage(response, model, phase)

    @synchronized_inference
    def generate_director_plan(self, prompt: str, schema: type[BaseModel] | None = None) -> str:
        """
        導演藍圖生成：one-shot 結構化輸出，回傳 JSON 字串（與 ``GeminiModelManager`` 同契約）。

        模型由 ``CLAUDE_DIRECTOR_MODEL`` 決定（預設 Opus 4.8，env 可切 Sonnet 做省錢 A/B）。
        ``schema`` 非 None 時走 structured outputs，回傳已驗證的 ``parsed_output`` 再轉 JSON 字串；
        ``schema`` 為 None（理論上 director 一律帶 schema）退化為純文字，取第一個 text block。
        例外往上拋（比照 Gemini 的 director 路徑，由 job / service 層處理）。
        """
        model = CLAUDE_DIRECTOR_MODEL
        if schema is not None:
            response = self.client.messages.parse(
                model=model,
                max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
                thinking=_ADAPTIVE_THINKING,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
            # 記錄 token 用量（Phase 4）；reflection 重試會多次呼叫、各自累加
            self._record(response, model)
            # parsed_output 為 SDK 已驗證的 schema 實例 → 轉回 JSON 字串供下游 json.loads
            return response.parsed_output.model_dump_json()

        # 無 schema 後備：純文字生成，取第一個 text block（維持回傳 str 契約）
        response = self.client.messages.create(
            model=model,
            max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
            thinking=_ADAPTIVE_THINKING,
            messages=[{"role": "user", "content": prompt}],
        )
        self._record(response, model)
        return next((block.text for block in response.content if block.type == "text"), "")
