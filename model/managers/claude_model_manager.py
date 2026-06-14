"""
ClaudeModelManager：雲端導演大腦 (Claude)，透過 Anthropic SDK 完成 Phase 4 導演藍圖的
agentic 推理。與 ``GeminiModelManager`` 平行，專責 director blueprint 這條接縫。

設計模式
--------
- **Template Method**：繼承 ``BaseModelManager``，Singleton 與鎖序由基底提供；
  子類只需實作 ``_initialize`` 與業務方法 ``generate_director_plan``。
- **Strategy**：``PromptManager`` 可由外部注入（``set_prompt_manager``），與 Gemini 對稱。
- **Adapter**：把 Anthropic 的 usage 物件交由 ``record_anthropic_usage`` 轉成共同成本帳本記錄。

輸出格式策略（為何不用 Anthropic structured outputs）
----------------------------------------------------
``DirectorBlueprint`` 是大型巢狀 schema（timeline + text_overlays + 多組 enum），Anthropic 原生
structured outputs 會回 400 ``Schema is too complex``（Gemini 的 ``response_schema`` 容忍度較高故無此限）。
因此 Claude **不走** native structured output，改比照本地 Qwen 路徑：以 ``schema_to_text`` 把**同一份**
schema 序列化進 prompt（SSOT、不另手抄、不會飄移），由 Claude 依文字結構輸出 JSON，下游
``SchedulingState`` 以既有 robust parser 解析。``schema_to_text`` 的開頭已含「直接輸出 JSON、不要
markdown」指示，故輸出可被穩定解析。

GPU 策略
--------
雲端 API 模型不佔本地 GPU；未設 ``self.device`` → ``_uses_gpu()`` 自動回 False，
forward 跳過 L2 GpuGate 與 ModelPool VRAM 重檢（與 Gemini 同路，不進 warmup / 資源池）。
"""
import json
import os

import anthropic
from pydantic import BaseModel

from config.model_config import (
    CLAUDE_DIRECTOR_MAX_TOKENS,
    CLAUDE_DIRECTOR_MODEL,
    DIRECTOR_USE_TOOL_USE,
)
from model.infra.base_model_manager import BaseModelManager, synchronized_inference
from model.infra.usage_ledger import phase_for_mode, record_anthropic_usage
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.schemas import schema_to_text
from prompt_manager.task_mode import TaskMode

# adaptive thinking：導演藍圖屬複雜 agentic 推理，讓 Claude 自行決定思考深度。
# Opus 4.x 僅支援 adaptive（用 budget_tokens 會 400）；effort 省略 = 預設 high。
_ADAPTIVE_THINKING = {"type": "adaptive"}

# tool use 的工具名（具名常數）：導演把最終藍圖以此 tool 的 input 結構化回傳。
_BLUEPRINT_TOOL_NAME = "submit_blueprint"


class ClaudeModelManager(BaseModelManager):
    """雲端導演大腦 (Claude)：Phase 4 導演藍圖的 agentic 推理。"""

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
        導演藍圖生成：one-shot 生成，回傳 JSON 字串（與 ``GeminiModelManager`` 同契約）。

        模型由 ``CLAUDE_DIRECTOR_MODEL`` 決定（預設 Opus 4.8）。主路徑走 **tool use**：schema 當 tool 的
        ``input_schema``，模型回傳 SDK 已解析的 dict，由我方 ``json.dumps`` 成字串——不再手 parse 自由
        文字，根除漏逗號類失敗，且對複雜 schema 容忍度遠高於 native structured output。
        ``DIRECTOR_USE_TOOL_USE=False`` 或無 schema 時走自由文字 + schema_to_text。例外往上拋。
        """
        model = CLAUDE_DIRECTOR_MODEL
        if schema is not None and DIRECTOR_USE_TOOL_USE:
            return self._generate_via_tool(prompt, schema, model)
        return self._generate_freetext(prompt, schema, model)

    def _create_message(self, **kwargs):
        """
        以 streaming 發出 Messages 請求並回傳組裝完成的 Message（content blocks / stop_reason / usage
        結構與非串流一致，下游邏輯無須改動）。

        導演 ``max_tokens`` 偏高（adaptive thinking + 整份藍圖共用額度），非串流的 ``messages.create``
        會被 SDK 以「可能 >10 分鐘需串流」擋下（ValueError）；串流是官方對長請求的建議做法，故導演
        一律走這條。串流會在 ``get_final_message()`` 阻塞至生成完成，故對呼叫端等同一次同步呼叫。
        """
        with self.client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()

    def _generate_via_tool(self, prompt: str, schema: type[BaseModel], model: str) -> str:
        """
        以 tool use 取結構化輸出：schema 當 tool 的 ``input_schema``，模型回傳 SDK 已解析的 dict，
        再 ``json.dumps`` 回字串維持與 Gemini 對稱的契約。

        adaptive thinking 開啟時 ``tool_choice`` 只能 ``auto``（無法強制特定 tool）。每次都印一行觀測
        日誌（stop_reason / blocks / used_tool）以便確認模型是否真的呼叫了 tool。模型未呼叫 tool 時：
        有文字就退回文字交下游容錯；連文字都空（常見於 max_tokens 在 thinking 階段就耗盡）則以自由文字
        路徑同輪救援一次，避免空草稿白白觸發整輪重生。本方法不掛 ``@synchronized_inference``：由已持鎖
        的 ``generate_director_plan`` 直呼，避免非重入鎖二次取用。
        """
        tool = {
            "name": _BLUEPRINT_TOOL_NAME,
            "description": "提交最終導演剪輯藍圖。務必呼叫本工具、依 input_schema 結構填寫，不要用純文字回覆。",
            "input_schema": schema.model_json_schema(),
        }
        response = self._create_message(
            model=model,
            max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
            thinking=_ADAPTIVE_THINKING,
            tools=[tool],
            tool_choice={"type": "auto"},  # 開 thinking 時不能強制特定 tool，只能 auto
            messages=[{"role": "user", "content": prompt}],
        )
        self._record(response, model)  # 記錄 token 用量（Phase 4）

        # 觀測性：印出 stop_reason 與各 block 型別，據此判斷模型有沒有真的呼叫 tool
        tool_input = next(
            (block.input for block in response.content if block.type == "tool_use"),
            None,
        )
        print(
            f"[Claude Director] stop_reason={response.stop_reason} "
            f"blocks={[block.type for block in response.content]} "
            f"used_tool={tool_input is not None}"
        )
        if tool_input is not None:
            return json.dumps(tool_input, ensure_ascii=False)

        # 模型未呼叫 tool：先給可行動診斷（最常見是 thinking 把 max_tokens 耗盡 → 來不及呼叫 tool）
        if response.stop_reason == "max_tokens":
            print(
                "[Claude Director] ⚠️ 輸出被 max_tokens 截斷（adaptive thinking + tool 輸出超過上限），"
                "模型來不及產出 tool 呼叫 → 調高 CLAUDE_DIRECTOR_MAX_TOKENS"
            )
        # 有文字 → 交下游容錯解析；連文字都空 → 以自由文字路徑同輪救援一次（避免空草稿觸發整輪重生）
        text = self._extract_text(response)
        if text.strip():
            return text
        print(
            f"[Claude Director] ⚠️ 未呼叫 {_BLUEPRINT_TOOL_NAME} 且無文字輸出"
            f"（stop_reason={response.stop_reason}）→ 以自由文字路徑救援重試一次"
        )
        return self._generate_freetext(prompt, schema, model)

    def _generate_freetext(self, prompt: str, schema: type[BaseModel] | None, model: str) -> str:
        """
        自由文字 + ``schema_to_text`` 生成路徑（``DIRECTOR_USE_TOOL_USE=False``、無 schema、或 tool use
        無輸出時的救援）。schema_to_text 已含「只輸出 JSON、不要 markdown」指示，下游以 robust parser
        解析。本方法不掛 ``@synchronized_inference``（由已持鎖的呼叫端直呼）。
        """
        content = f"{prompt}\n\n{schema_to_text(schema)}" if schema is not None else prompt
        response = self._create_message(
            model=model,
            max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
            thinking=_ADAPTIVE_THINKING,
            messages=[{"role": "user", "content": content}],
        )
        self._record(response, model)  # 記錄 token 用量（Phase 4）
        return self._extract_text(response)

    @staticmethod
    def _extract_text(response) -> str:
        """從 Anthropic 回應取第一段文字內容（略過 adaptive thinking 的 thinking block）；無則回空字串。"""
        return next((block.text for block in response.content if block.type == "text"), "")
