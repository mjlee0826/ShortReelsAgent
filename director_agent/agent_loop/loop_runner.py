"""
導演 agentic loop 主迴圈 (Template Method)。

驅動多輪 tool-use 對話：每輪呼叫 manager 串流一回合 → 原樣保留完整 ``response.content``（thinking +
tool_use blocks，續傳必備）→ 分派工具 → 把結果當 tool_result 餵回。``submit_blueprint`` 後跑
:class:`CriticGate`：通過即結束、回最終藍圖；有錯把錯誤當 tool_result 餵回同一對話讓導演就地修。
``ask_user`` 則序列化續跑狀態並拋 :class:`ClarificationRequested`（B2 suspend），交 director_service
落地 session、釋鎖、之後由 ``/generate/resume`` 接答案 :meth:`resume` 續跑。以 ``max_steps`` 與
``max_critic_retries`` 收斂，杜絕無限往返扣款。
"""
from __future__ import annotations

from director_agent.agent_loop.agent_context import AgentContext
from director_agent.agent_loop.critic_gate import CriticGate
from director_agent.agent_loop.exceptions import ClarificationRequested
from director_agent.agent_loop.tools.tool_registry import ToolRegistry

# 達步數 / 重試上限仍無有效藍圖時，no-tool-use 回合用此 nudge 要模型收斂提交
_SUBMIT_NUDGE = "請依工作流完成並呼叫 submit_blueprint 提交藍圖。"

# 送回 API 當 input 時，各 block 型別合法的 input 欄位白名單；其餘（如 text block 的
# parsed_output 等 output-only 欄位）一律剔除，否則 API 回 400 Extra inputs are not permitted。
_INPUT_BLOCK_FIELDS = {
    "text": ("type", "text", "citations"),
    "thinking": ("type", "thinking", "signature"),
    "redacted_thinking": ("type", "data"),
    "tool_use": ("type", "id", "name", "input"),
}


def _block_to_input_dict(block) -> dict:
    """
    把一個 assistant content block 轉成『可當 API input 重送』的乾淨 dict。

    Anthropic 回應的 block（model_dump 後）會帶 output-only 欄位（如 text block 的 ``parsed_output``），
    這些欄位不在 input schema 內，原樣回送會 400 ``Extra inputs are not permitted``。故依 block 型別只
    保留白名單欄位（值為 None 者一併剔除）；thinking 的 ``signature`` 在白名單內，續傳不會 400。
    """
    raw = block.model_dump() if hasattr(block, "model_dump") else dict(block)
    allowed = _INPUT_BLOCK_FIELDS.get(raw.get("type"))
    if allowed is None:
        return raw  # 未知型別：保守原樣帶過
    return {key: raw[key] for key in allowed if raw.get(key) is not None}


def _serialize_messages(messages: list) -> list:
    """
    把對話 messages 轉成可 JSON 落地的形式（B2 session 持久化用）。

    assistant 回合的 content 是 Anthropic block 物件（thinking / tool_use / text）或 _loop 已轉好的
    input dict，一律過 :func:`_block_to_input_dict` 收斂成乾淨 input dict（剔除 parsed_output 等
    output-only 欄位、保留 thinking 的 signature）；user 回合的 content（字串 / tool_result /
    image dict）本就可序列化，原樣帶過。
    """
    serialized = []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            # list 內皆為 block 物件 / input dict（assistant）或 tool_result / image dict（user）；
            # 一律過 _block_to_input_dict：白名單外型別（tool_result / image）原樣回傳，idempotent。
            content = [_block_to_input_dict(block) for block in content]
        serialized.append({"role": message["role"], "content": content})
    return serialized


class DirectorAgentLoop:
    """導演 agentic loop 驅動器（Template Method）。"""

    def __init__(
        self,
        manager,
        registry: ToolRegistry,
        critic_gate: CriticGate,
        max_steps: int,
        max_critic_retries: int,
    ):
        """注入串流 manager、工具註冊表、Critic 閘與兩個收斂上限。"""
        self.manager = manager
        self.registry = registry
        self.critic_gate = critic_gate
        self.max_steps = max_steps
        self.max_critic_retries = max_critic_retries

    def run(self, system_prompt: str, initial_user_message: str, ctx: AgentContext) -> dict:
        """全新開跑：以首則 user 訊息起一輪 loop，回最終藍圖 dict。"""
        messages: list = [{"role": "user", "content": initial_user_message}]
        return self._loop(system_prompt, messages, ctx)

    def resume(self, resume_state: dict, answer: str, ctx: AgentContext) -> dict:
        """
        B2 續跑：把使用者答案接成 ask_user 的 tool_result（連同暫停當下同回合其餘工具結果），續跑 loop。

        ``ctx`` 由 director_service 依持久化的 viewed / corrections 還原後傳入，使必讀強制 / 修正狀態延續。
        """
        system_prompt = resume_state["system_prompt"]
        messages: list = list(resume_state.get("messages") or [])
        resume_turn: list = list(resume_state.get("pending_tool_results") or [])
        resume_turn.append({
            "type": "tool_result",
            "tool_use_id": resume_state["ask_user_tool_use_id"],
            "content": answer,
        })
        messages.append({"role": "user", "content": resume_turn})
        return self._loop(system_prompt, messages, ctx)

    # ── 共用迴圈體 ────────────────────────────────────────────────────────────
    def _loop(self, system_prompt: str, messages: list, ctx: AgentContext) -> dict:
        """
        多輪 tool-use 迴圈（run / resume 共用）。回最終藍圖；ask_user 時拋 ClarificationRequested。

        達 max_steps 仍未提交時，回最後一次提交的草稿（若有），否則拋 ``RuntimeError``。
        """
        critic_retries = 0
        last_blueprint: dict | None = None

        def on_thinking(text: str) -> None:
            """串流導演思考 delta 到前端（無 tracker 則 no-op）。"""
            if ctx.tracker is not None and text:
                ctx.tracker.emit_director_thinking_delta(text)

        for _step in range(self.max_steps):
            response = self.manager.stream_director_turn(
                system=system_prompt,
                messages=messages,
                tools=self.registry.anthropic_tools(),
                on_thinking_delta=on_thinking,
            )
            # append 完整 assistant content（含 thinking + tool_use，續傳必備），但先收斂成乾淨 input
            # dict：剔除 parsed_output 等 output-only 欄位，否則回送 API 會 400（live 多輪與 resume 一致）
            messages.append({
                "role": "assistant",
                "content": [_block_to_input_dict(b) for b in response.content],
            })

            tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if not tool_uses:
                if last_blueprint is not None:
                    return last_blueprint
                messages.append({"role": "user", "content": _SUBMIT_NUDGE})
                continue

            tool_results: list = []
            pending_clarification: dict | None = None
            clarification_tool_use_id: str = ""
            for block in tool_uses:
                execution = self.registry.dispatch(block.name, block.input, ctx)
                if ctx.tracker is not None and execution.narration:
                    ctx.tracker.emit_director_tool_call(block.name, execution.narration)

                # ask_user：記下，其 tool_result = 使用者答案，續跑時才補（本回合不加）
                if execution.clarification is not None:
                    pending_clarification = execution.clarification
                    clarification_tool_use_id = block.id
                    continue

                # submit_blueprint：跑 CriticGate 決定 terminal 或餵回
                if execution.submitted_blueprint is not None:
                    blueprint = execution.submitted_blueprint
                    last_blueprint = blueprint
                    outcome = self._handle_submit(blueprint, block.id, critic_retries, ctx)
                    if outcome.terminal:
                        return blueprint
                    critic_retries = outcome.critic_retries
                    tool_results.append(outcome.tool_result)
                    continue

                # 一般工具：把結果當 tool_result 餵回
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": execution.content,
                }
                if execution.is_error:
                    tool_result["is_error"] = True
                tool_results.append(tool_result)

            # 本回合有人問使用者 → 序列化續跑狀態並暫停（B2）
            if pending_clarification is not None:
                self._raise_clarification(
                    system_prompt, messages, tool_results,
                    clarification_tool_use_id, pending_clarification, ctx,
                )

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        if last_blueprint is not None:
            print("⚠️ [DirectorAgentLoop] 達步數上限，輸出最後一次提交的草稿（可能仍有 Critic 錯誤）。")
            return last_blueprint
        raise RuntimeError("導演 agentic loop 達步數上限仍未提交有效藍圖")

    def _raise_clarification(
        self, system_prompt, messages, pending_tool_results, ask_user_tool_use_id,
        clarification, ctx: AgentContext,
    ) -> None:
        """組可序列化的續跑狀態並拋 ClarificationRequested（B2 暫停）。"""
        resume_state = {
            "system_prompt": system_prompt,
            "messages": _serialize_messages(messages),
            "pending_tool_results": pending_tool_results,
            "ask_user_tool_use_id": ask_user_tool_use_id,
            # tuple → list 以利 JSON 落地；resume 還原時再轉回
            "viewed": {aid: [list(rng) for rng in ranges] for aid, ranges in ctx.viewed.items()},
            "corrections": ctx.corrections,
        }
        if ctx.tracker is not None:
            ctx.tracker.emit_director_tool_call("ask_user", "等待使用者回答…")
        raise ClarificationRequested(
            clarification.get("question", ""), clarification.get("options", []), resume_state
        )

    def _handle_submit(self, blueprint: dict, tool_use_id: str, critic_retries: int, ctx: AgentContext):
        """
        處理一次 submit_blueprint：跑 CriticGate，回 :class:`_SubmitOutcome`。

        通過（或達重試上限）→ terminal=True；否則把錯誤組成 is_error 的 tool_result 餵回，並回新的
        critic_retries 計數。CriticGate 帶 ctx 以一併做必讀強制驗證。
        """
        errors, repairs = self.critic_gate.validate(blueprint, list(ctx.asset_index.values()), ctx)
        if repairs:
            print(f"🔧 [DirectorAgentLoop] 自動修補 {len(repairs)} 項：")
            for fix in repairs:
                print(f"   - {fix}")

        if not errors:
            if ctx.tracker is not None:
                ctx.tracker.emit_director_tool_call("submit_blueprint", "藍圖驗證通過 ✅")
            return _SubmitOutcome(terminal=True, critic_retries=critic_retries, tool_result=None)

        critic_retries += 1
        if ctx.tracker is not None:
            ctx.tracker.emit_director_tool_call(
                "submit_blueprint", f"驗證發現 {len(errors)} 個錯誤（第 {critic_retries} 次）"
            )
        if critic_retries >= self.max_critic_retries:
            print(f"🚨 [DirectorAgentLoop] 達 Critic 重試上限（{self.max_critic_retries}），輸出當前草稿。")
            return _SubmitOutcome(terminal=True, critic_retries=critic_retries, tool_result=None)

        err_text = (
            "藍圖未通過物理驗證，請『只』修正以下錯誤後重新 submit_blueprint（索引 [N] 為 timeline 第 N 段）：\n"
            + "\n".join(f"- {err}" for err in errors)
        )
        return _SubmitOutcome(
            terminal=False,
            critic_retries=critic_retries,
            tool_result={
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": err_text,
                "is_error": True,
            },
        )


class _SubmitOutcome:
    """submit 處理結果（loop 內部值物件）：是否終止 / 新的重試計數 / 要餵回的 tool_result。"""

    __slots__ = ("terminal", "critic_retries", "tool_result")

    def __init__(self, terminal: bool, critic_retries: int, tool_result):
        self.terminal = terminal
        self.critic_retries = critic_retries
        self.tool_result = tool_result


def build_director_registry(has_template: bool = False) -> ToolRegistry:
    """
    組裝導演工具註冊表（工廠）。

    基礎工具：``get_fields`` / ``view_raw`` / ``correct_metadata`` / ``get_music_beats`` / ``ask_user`` /
    ``submit_blueprint``。``has_template`` 時才加掛 ``view_template``（無範本就不註冊，避免導演看到一個
    沒用的工具而誤呼叫）。工具皆無狀態（於 execute 收 ctx），可安全共用單一 registry 實例；延遲 import
    避免時序耦合。
    """
    from director_agent.agent_loop.tools.ask_user_tool import AskUserTool
    from director_agent.agent_loop.tools.correct_metadata_tool import CorrectMetadataTool
    from director_agent.agent_loop.tools.get_fields_tool import GetFieldsTool
    from director_agent.agent_loop.tools.get_music_beats_tool import GetMusicBeatsTool
    from director_agent.agent_loop.tools.submit_blueprint_tool import SubmitBlueprintTool
    from director_agent.agent_loop.tools.view_raw_tool import ViewRawTool

    tools = [
        GetFieldsTool(),
        ViewRawTool(),
        CorrectMetadataTool(),
        GetMusicBeatsTool(),
        AskUserTool(),
        SubmitBlueprintTool(),
    ]
    if has_template:
        # 緊接 view_raw 之後加掛，讓「看素材 / 看範本」兩個視覺工具相鄰、語意成對
        from director_agent.agent_loop.tools.view_template_tool import ViewTemplateTool
        tools.insert(2, ViewTemplateTool())
    return ToolRegistry(tools)
