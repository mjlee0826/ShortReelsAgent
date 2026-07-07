"""
ClaudeModelManager：雲端導演大腦 (Claude)，透過 Anthropic SDK 完成 Phase 4 導演藍圖的
agentic 推理。與 ``GeminiModelManager`` 平行，專責 director blueprint 這條接縫。

設計模式
--------
- **Template Method**：繼承 ``BaseModelManager``，Singleton 與鎖序由基底提供；
  子類只需實作 ``_initialize`` 與業務方法 ``stream_director_turn`` / ``generate_structured``。
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

from config.director_config import DIRECTOR_TASK_BUDGET_TOKENS
from config.model_config import (
    CLAUDE_DIRECTOR_MAX_TOKENS,
    CLAUDE_DIRECTOR_MODEL,
)
from model.infra.base_model_manager import BaseModelManager, synchronized_inference
from model.infra.usage_ledger import phase_for_mode, record_anthropic_usage
from shared.json_utils import parse_json_lenient
from prompt_manager.base_prompt_manager import BasePromptManager
from prompt_manager.default_prompt_manager import DefaultPromptManager
from prompt_manager.schemas import schema_to_text
from prompt_manager.task_mode import TaskMode
import logging

logger = logging.getLogger(__name__)

# adaptive thinking：導演藍圖屬複雜 agentic 推理，讓 Claude 自行決定思考深度。
# Opus 4.x 僅支援 adaptive（用 budget_tokens 會 400）；effort 省略 = 預設 high。
_ADAPTIVE_THINKING = {"type": "adaptive"}

# agentic loop 串流版：開 display="summarized" 才有可讀思考可即時串給前端
# （Opus 4.8 預設 omitted 會是空字串，前端只看到一段長時間空白）。
_ADAPTIVE_THINKING_SUMMARIZED = {"type": "adaptive", "display": "summarized"}

# Task Budget 的 beta header（DIRECTOR_TASK_BUDGET_TOKENS > 0 時才走此 beta 路徑）。
_TASK_BUDGET_BETA = "task-budgets-2026-03-13"

# tool use 的工具名（具名常數）：導演把最終藍圖以此 tool 的 input 結構化回傳。
_BLUEPRINT_TOOL_NAME = "submit_blueprint"


def _with_cache_breakpoint(messages: list) -> list:
    """
    回一份 messages 副本，對最後一則訊息的最後一個 content block 加 ``cache_control``（對話前綴遞增快取）。

    送出時 ``messages[-1]`` 恆為 user 回合（字串 / tool_result / image dict 的 list），故只處理 user content：
    字串 → 包成帶 cache_control 的 text block；list → 對最後一項加 cache_control。**非破壞性**（不改原
    list / block），避免快取標記寫回 loop 的 messages 而污染 B2 持久化。
    """
    if not messages:
        return messages
    out = list(messages)
    last = dict(out[-1])
    content = last.get("content")
    mark = {"type": "ephemeral"}
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content, "cache_control": mark}]
    elif isinstance(content, list) and content and isinstance(content[-1], dict):
        new_content = list(content)
        tail = dict(new_content[-1])
        tail["cache_control"] = mark
        new_content[-1] = tail
        last["content"] = new_content
    else:
        return messages  # 末塊非可標記型別（理論上不會發生於 user 回合）：不加斷點
    out[-1] = last
    return out


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

    def _record(self, response, model: str, mode: TaskMode = TaskMode.DIRECTOR_BLUEPRINT) -> None:
        """把本次呼叫的 token 用量記入當前成本帳本（無帳本則 no-op）；phase 由 ``mode`` 推得。

        導演 loop 走預設 DIRECTOR_BLUEPRINT（Phase 4）；配樂 brief 等旁支任務傳入自己的 mode，
        讓成本正確歸戶（brief → MUSIC_SEARCH_QUERY → Phase 3），不再全掛在 Phase 4 名下。
        """
        phase = phase_for_mode(mode)
        if phase is not None:
            record_anthropic_usage(response, model, phase)

    @synchronized_inference
    def stream_director_turn(
        self,
        system: str,
        messages: list,
        tools: list,
        on_thinking_delta=None,
        on_text_delta=None,
    ):
        """
        導演 agentic loop 的「一回合」串流推論：發一次帶 tools 的 Messages 請求，邊串流邊把
        thinking / 文字 delta 經 callback 吐出（供前端即時呈現），回傳組裝完成的 ``Message``。

        本方法是多輪 loop 的單步（不同於一次性的結構化呼叫），呼叫端負責維護
        ``messages`` —— 每輪須原樣 append 完整 ``response.content``（含 thinking + tool_use blocks）：
        開 thinking 時續傳必須帶回未修改的 thinking block，否則 API 回 400。

        - thinking 開 ``display="summarized"`` 才有可讀思考可串（預設 omitted 會是空字串）。
        - 開 thinking 時 ``tool_choice`` 只能 ``auto``（無法強制特定 tool），故終止由呼叫端的
          max_steps + submit_blueprint 收斂。
        - ``DIRECTOR_TASK_BUDGET_TOKENS > 0`` 時走 beta（task budget，讓模型自我節制整輪預算）；
          否則走最穩定的非 beta 串流路徑。token 用量沿用 :meth:`_record` 記入 Phase 4 帳本。
        本方法不另解析輸出：呼叫端（loop）自行從 ``response.content`` 取 tool_use blocks 分派。
        """
        model = CLAUDE_DIRECTOR_MODEL
        kwargs = dict(
            model=model,
            max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
            # system 帶 cache_control：快取 tools + system（render 序 tools→system，斷點在 system 末塊即含 tools）
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            thinking=_ADAPTIVE_THINKING_SUMMARIZED,
            tools=tools,
            tool_choice={"type": "auto"},  # 開 thinking 時不能強制特定 tool
            # messages 末塊加 cache_control：對話前綴遞增快取（send-time，非破壞性，不寫回 loop messages）
            messages=_with_cache_breakpoint(messages),
        )
        if DIRECTOR_TASK_BUDGET_TOKENS > 0:
            # beta：把整輪 token 預算告知模型（API 要求 total ≥ 20000）
            stream_ctx = self.client.beta.messages.stream(
                betas=[_TASK_BUDGET_BETA],
                output_config={
                    "task_budget": {"type": "tokens", "total": DIRECTOR_TASK_BUDGET_TOKENS}
                },
                **kwargs,
            )
        else:
            stream_ctx = self.client.messages.stream(**kwargs)

        with stream_ctx as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                delta = event.delta
                delta_type = getattr(delta, "type", "")
                if delta_type == "thinking_delta" and on_thinking_delta is not None:
                    on_thinking_delta(getattr(delta, "thinking", ""))
                elif delta_type == "text_delta" and on_text_delta is not None:
                    on_text_delta(getattr(delta, "text", ""))
            response = stream.get_final_message()

        self._record(response, model)  # 記錄 token 用量（Phase 4）
        # 觀測快取命中：read 高 = 前綴命中（~0.1× 價）；write = 本輪寫入快取（~1.25×）
        usage = getattr(response, "usage", None)
        if usage is not None:
            logger.info(
                f"[Claude Director] cache read={getattr(usage, 'cache_read_input_tokens', 0)} "
                f"write={getattr(usage, 'cache_creation_input_tokens', 0)} "
                f"input={getattr(usage, 'input_tokens', 0)}"
            )
        return response

    @synchronized_inference
    def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        model: str | None = None,
        thinking_enabled: bool = True,
        task_mode: TaskMode = TaskMode.DIRECTOR_BLUEPRINT,
    ) -> dict:
        """
        one-shot 結構化輸出（tool use）：回 parsed dict。供配樂 brief 等小型結構化任務重用。

        走 :meth:`_generate_via_tool` 的 tool-use 路徑（schema 當 tool ``input_schema``），但回
        已解析的 dict（容錯解析，失敗回空 dict）。不掛多輪、不串流，純一次結構化呼叫。

        :param model: 指定模型；None 沿用導演模型（向後相容）。小任務可傳 Haiku 等便宜模型。
        :param thinking_enabled: False 時整包省略 thinking 參數（Haiku 等小任務不需思考、
            且省思考 token 費），並改為**強制** ``tool_choice`` 指定 tool——thinking 關閉時 API
            允許強制，從根拔除「模型沒呼叫 tool」的失敗模式（開 thinking 時只能 auto）。
        :param task_mode: 成本歸戶用的 TaskMode（brief 傳 MUSIC_SEARCH_QUERY → Phase 3）。
        """
        raw = self._generate_via_tool(
            prompt, schema, model or CLAUDE_DIRECTOR_MODEL,
            thinking_enabled=thinking_enabled, task_mode=task_mode,
        )
        return parse_json_lenient(raw, default={})

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

    def _generate_via_tool(
        self,
        prompt: str,
        schema: type[BaseModel],
        model: str,
        thinking_enabled: bool = True,
        task_mode: TaskMode = TaskMode.DIRECTOR_BLUEPRINT,
    ) -> str:
        """
        以 tool use 取結構化輸出：schema 當 tool 的 ``input_schema``，模型回傳 SDK 已解析的 dict，
        再 ``json.dumps`` 回字串維持與 Gemini 對稱的契約。

        adaptive thinking 開啟時 ``tool_choice`` 只能 ``auto``（無法強制特定 tool）；
        ``thinking_enabled=False``（Haiku 等小任務）時整包省略 thinking 並**強制**指定 tool，
        結構化輸出不再依賴模型自願呼叫。每次都印一行觀測日誌（stop_reason / blocks / used_tool）
        以便確認模型是否真的呼叫了 tool。模型未呼叫 tool 時：有文字就退回文字交下游容錯；
        連文字都空（常見於 max_tokens 在 thinking 階段就耗盡）則以自由文字路徑同輪救援一次，
        避免空草稿白白觸發整輪重生。本方法不掛 ``@synchronized_inference``：由已持鎖
        的 ``generate_structured`` 直呼，避免非重入鎖二次取用。
        """
        tool = {
            "name": _BLUEPRINT_TOOL_NAME,
            "description": "提交最終導演剪輯藍圖。務必呼叫本工具、依 input_schema 結構填寫，不要用純文字回覆。",
            "input_schema": schema.model_json_schema(),
        }
        kwargs = dict(
            model=model,
            max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
            tools=[tool],
            messages=[{"role": "user", "content": prompt}],
        )
        if thinking_enabled:
            kwargs["thinking"] = _ADAPTIVE_THINKING
            kwargs["tool_choice"] = {"type": "auto"}  # 開 thinking 時不能強制特定 tool，只能 auto
        else:
            # 無 thinking：可強制指定 tool，從根拔除「模型沒呼叫 tool」的失敗模式
            kwargs["tool_choice"] = {"type": "tool", "name": _BLUEPRINT_TOOL_NAME}
        response = self._create_message(**kwargs)
        self._record(response, model, task_mode)  # 記錄 token 用量（phase 依 task_mode 歸戶）

        # 觀測性：印出 stop_reason 與各 block 型別，據此判斷模型有沒有真的呼叫 tool
        tool_input = next(
            (block.input for block in response.content if block.type == "tool_use"),
            None,
        )
        logger.info(
            f"[Claude Director] stop_reason={response.stop_reason} "
            f"blocks={[block.type for block in response.content]} "
            f"used_tool={tool_input is not None}"
        )
        if tool_input is not None:
            return json.dumps(tool_input, ensure_ascii=False)

        # 模型未呼叫 tool：先給可行動診斷（最常見是 thinking 把 max_tokens 耗盡 → 來不及呼叫 tool）
        if response.stop_reason == "max_tokens":
            logger.info(
                "[Claude Director] ⚠️ 輸出被 max_tokens 截斷（adaptive thinking + tool 輸出超過上限），"
                "模型來不及產出 tool 呼叫 → 調高 CLAUDE_DIRECTOR_MAX_TOKENS"
            )
        # 有文字 → 交下游容錯解析；連文字都空 → 以自由文字路徑同輪救援一次（避免空草稿觸發整輪重生）
        text = self._extract_text(response)
        if text.strip():
            return text
        logger.info(
            f"[Claude Director] ⚠️ 未呼叫 {_BLUEPRINT_TOOL_NAME} 且無文字輸出"
            f"（stop_reason={response.stop_reason}）→ 以自由文字路徑救援重試一次"
        )
        return self._generate_freetext(
            prompt, schema, model, thinking_enabled=thinking_enabled, task_mode=task_mode
        )

    def _generate_freetext(
        self,
        prompt: str,
        schema: type[BaseModel] | None,
        model: str,
        thinking_enabled: bool = True,
        task_mode: TaskMode = TaskMode.DIRECTOR_BLUEPRINT,
    ) -> str:
        """
        自由文字 + ``schema_to_text`` 生成路徑（``DIRECTOR_USE_TOOL_USE=False``、無 schema、或 tool use
        無輸出時的救援）。schema_to_text 已含「只輸出 JSON、不要 markdown」指示，下游以 robust parser
        解析。本方法不掛 ``@synchronized_inference``（由已持鎖的呼叫端直呼）。
        """
        content = f"{prompt}\n\n{schema_to_text(schema)}" if schema is not None else prompt
        kwargs = dict(
            model=model,
            max_tokens=CLAUDE_DIRECTOR_MAX_TOKENS,
            messages=[{"role": "user", "content": content}],
        )
        if thinking_enabled:
            kwargs["thinking"] = _ADAPTIVE_THINKING
        response = self._create_message(**kwargs)
        self._record(response, model, task_mode)  # 記錄 token 用量（phase 依 task_mode 歸戶）
        return self._extract_text(response)

    @staticmethod
    def _extract_text(response) -> str:
        """從 Anthropic 回應取第一段文字內容（略過 adaptive thinking 的 thinking block）；無則回空字串。"""
        return next((block.text for block in response.content if block.type == "text"), "")
