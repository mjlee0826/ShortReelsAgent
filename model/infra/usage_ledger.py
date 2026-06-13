"""
Gemini 用量帳本與成本記錄 (per-job 累加 + contextvars 攜帶)。

職責
----
把每次 Gemini 呼叫的 ``usage_metadata``(純 token 數)依**官方價目表**換算成推估金額,
依 Phase 累加,供 ``director_service`` 在 job 收尾輸出「分階段花費」。

設計重點
--------
- **Null Object**:未綁定帳本(CLI / 無 job)時 ``record_usage`` 直接 no-op,不影響呼叫端。
- **Phase 由 TaskMode 推導**:每個 Gemini 呼叫點都已知自己的 ``TaskMode``,而 TaskMode→Phase
  是固定映射,故不需 ``phase_scope`` 之類的當前狀態;歸戶在記錄當下即確定,不會標錯。
- **執行緒安全**:Phase 1 的 pipeline 多緒並發記錄,以 Lock 保護累加串列。
- **跨緒攜帶**:帳本本身放 ContextVar;pipeline / preparer 的 ThreadPoolExecutor 在 submit
  時以 ``copy_context`` 複製父緒 context,讓 worker 緒讀得到同一本帳(見三處 submit 包覆)。

計價精度
--------
輸入優先 walk ``prompt_tokens_details`` 分模態計價(Level 1;影片+音訊任務需要),缺明細退回
總 token × 文字價(Level 0);輸出 = (candidates + thoughts) × 輸出價;快取命中以折扣價計。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional

from config.pricing_config import TOKENS_PER_MILLION, ModelPricing, get_pricing
from prompt_manager.task_mode import TaskMode

# 金額在輸出 dict 內的小數位數（避免浮點雜訊；cents 以下精度已足夠）
_COST_ROUND_DIGITS = 6


class Phase(Enum):
    """成本歸屬的階段標籤（與前端 / 輸出 dict 的鍵一致）。"""
    PHASE1 = "phase1"  # 感知分析（1b 深度圖片 + 1c 影片事件索引）
    PHASE2 = "phase2"  # 範本分析
    PHASE3 = "phase3"  # 配樂關鍵字
    PHASE4 = "phase4"  # 導演藍圖


# TaskMode → Phase 固定映射;BASIC_MEDIA_ANALYSIS 走本地 Qwen、不經 Gemini,故不列入。
TASKMODE_TO_PHASE: dict[TaskMode, Phase] = {
    TaskMode.DEEP_IMAGE_ANALYSIS: Phase.PHASE1,
    TaskMode.VIDEO_EVENT_INDEX: Phase.PHASE1,
    TaskMode.TEMPLATE_ANALYSIS: Phase.PHASE2,
    TaskMode.MUSIC_SEARCH_QUERY: Phase.PHASE3,
    TaskMode.DIRECTOR_BLUEPRINT: Phase.PHASE4,
    TaskMode.DIRECTOR_CASTING: Phase.PHASE4,    # 兩階段第一段選角，成本同歸 Phase 4
}


def phase_for_mode(mode: TaskMode) -> Optional[Phase]:
    """由 TaskMode 推出 Phase;本地任務(無對應)回 None,呼叫端據此略過記錄。"""
    return TASKMODE_TO_PHASE.get(mode)


@dataclass(frozen=True)
class UsageRecord:
    """單次 Gemini 呼叫的用量與推估成本。"""
    phase: Phase
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageLedger:
    """執行緒安全的成本累加器（每個 job 一本）。"""

    def __init__(self) -> None:
        """初始化空帳本與保護累加的鎖。"""
        self._records: list[UsageRecord] = []
        self._lock = threading.Lock()

    def add(self, record: UsageRecord) -> None:
        """記一筆用量（Phase 1 pipeline 多緒會並發呼叫，故加鎖）。"""
        with self._lock:
            self._records.append(record)

    def summary(self) -> dict:
        """彙整成逐 Phase 的 {tokens, 金額, 呼叫數, 模型} 與 total_usd（輸出 dict 用）。

        鍵為 Phase.value(如 ``"phase2"``);只列實際有呼叫的 Phase。記錄保留 model,
        故同一 Phase 跨多模型(如 Phase 1 的 1b+1c)會列出全部 models。
        """
        with self._lock:
            records = list(self._records)

        out: dict = {}
        total = 0.0
        for r in records:
            entry = out.setdefault(r.phase.value, {
                "input_tokens": 0, "output_tokens": 0,
                "cost_usd": 0.0, "calls": 0, "models": [],
            })
            entry["input_tokens"] += r.input_tokens
            entry["output_tokens"] += r.output_tokens
            entry["cost_usd"] += r.cost_usd
            entry["calls"] += 1
            if r.model not in entry["models"]:
                entry["models"].append(r.model)
            total += r.cost_usd

        # 金額四捨五入,避免浮點雜訊污染輸出
        for entry in out.values():
            entry["cost_usd"] = round(entry["cost_usd"], _COST_ROUND_DIGITS)
        out["total_usd"] = round(total, _COST_ROUND_DIGITS)
        return out

    def format_summary(self, title: str) -> str:
        """組出可 print 的多行字串（與 summary 同源，DRY），供 service 收尾輸出。"""
        data = self.summary()
        lines = [f"[Cost] {title}: total ${data.get('total_usd', 0.0):.6f}"]
        for phase in Phase:  # 依固定順序輸出,讀起來穩定
            entry = data.get(phase.value)
            if entry is None:
                continue
            models = ", ".join(entry["models"])
            lines.append(
                f"  {phase.value} | {models} | "
                f"in={entry['input_tokens']} out={entry['output_tokens']} | "
                f"${entry['cost_usd']:.6f}"
            )
        return "\n".join(lines)


# 唯一的 contextvar:當前 job 的帳本。預設 None = 無 job(Null Object,record_usage 略過)。
_active_ledger: ContextVar[Optional[UsageLedger]] = ContextVar("active_usage_ledger", default=None)


@contextmanager
def cost_session() -> Iterator[UsageLedger]:
    """開一本 job 級帳本並綁進 contextvar;離開時還原(支援巢狀/重入)。"""
    ledger = UsageLedger()
    token = _active_ledger.set(ledger)
    try:
        yield ledger
    finally:
        _active_ledger.reset(token)


def record_usage(response, model: str, phase: Phase) -> None:
    """讀 response.usage_metadata 計價並記入當前帳本;無帳本 / 無 usage 則 no-op。

    供 ``GeminiModelManager`` 在每個 Gemini 出口呼叫(analyze_media / director / music)。
    """
    ledger = _active_ledger.get()
    if ledger is None:  # Null Object:無 job 帳本時不記
        return
    usage = getattr(response, "usage_metadata", None)
    if usage is None:  # 某些錯誤回應可能無 usage
        return

    pricing = get_pricing(model)
    input_tokens = _safe_int(getattr(usage, "prompt_token_count", 0))
    # 思考 token 計費算輸出,務必併入(漏算會低估 Phase 4 等思考模型成本)
    output_tokens = (
        _safe_int(getattr(usage, "candidates_token_count", 0))
        + _safe_int(getattr(usage, "thoughts_token_count", 0))
    )
    cost = (
        _input_cost(usage, pricing)
        + output_tokens / TOKENS_PER_MILLION * pricing.output
    )
    ledger.add(UsageRecord(
        phase=phase, model=model,
        input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
    ))


def record_anthropic_usage(response, model: str, phase: Phase) -> None:
    """讀 Anthropic ``response.usage`` 計價並記入當前帳本；無帳本 / 無 usage 則 no-op。

    供 ``ClaudeModelManager`` 在 director 出口呼叫。與 Gemini 版 ``record_usage`` 對稱：兩者皆為
    「各家 usage 物件的 Adapter」，最終都寫進同一本 ``UsageLedger``，各自隔離供應商欄位差異。
    Anthropic 的 thinking token 已計入 ``output_tokens``（輸出價），無須像 Gemini 另外併入。
    """
    ledger = _active_ledger.get()
    if ledger is None:  # Null Object：無 job 帳本時不記
        return
    usage = getattr(response, "usage", None)
    if usage is None:  # 某些錯誤回應可能無 usage
        return

    pricing = get_pricing(model)
    # input_tokens 為「未命中快取」的輸入；命中快取者另計（director 走 one-shot、通常無快取）
    input_tokens = _safe_int(getattr(usage, "input_tokens", 0))
    cached_tokens = _safe_int(getattr(usage, "cache_read_input_tokens", 0))
    output_tokens = _safe_int(getattr(usage, "output_tokens", 0))
    cached_rate = pricing.cached_input if pricing.cached_input is not None else pricing.input_text
    cost = (
        input_tokens / TOKENS_PER_MILLION * pricing.input_text
        + cached_tokens / TOKENS_PER_MILLION * cached_rate
        + output_tokens / TOKENS_PER_MILLION * pricing.output
    )
    # input 統計併入快取部分，讓帳本反映實際輸入量（與 Gemini 版的歸戶口徑一致）
    ledger.add(UsageRecord(
        phase=phase, model=model,
        input_tokens=input_tokens + cached_tokens, output_tokens=output_tokens, cost_usd=cost,
    ))


def _input_cost(usage, pricing: ModelPricing) -> float:
    """算輸入成本:有模態明細走分模態(Level 1),否則總量 × 文字價(Level 0)。"""
    total_input = _safe_int(getattr(usage, "prompt_token_count", 0))
    cached = _safe_int(getattr(usage, "cached_content_token_count", 0))
    details = getattr(usage, "prompt_tokens_details", None) or []
    audio_rate = pricing.input_audio if pricing.input_audio is not None else pricing.input_text
    cached_rate = pricing.cached_input if pricing.cached_input is not None else pricing.input_text

    if details:
        # Level 1:逐模態加總(音訊另計、其餘文字價)。目前未開快取,快取與模態的交集從略。
        cost = 0.0
        counted = 0
        for d in details:
            tokens = _safe_int(getattr(d, "token_count", 0))
            counted += tokens
            rate = audio_rate if _is_audio_modality(getattr(d, "modality", None)) else pricing.input_text
            cost += tokens / TOKENS_PER_MILLION * rate
        # 明細未涵蓋全部時,差額以文字價補(防漏算)
        cost += max(total_input - counted, 0) / TOKENS_PER_MILLION * pricing.input_text
        return cost

    # Level 0 fallback:無模態明細 → 全部文字價,快取部分以折扣價
    billable = max(total_input - cached, 0)
    return (
        billable / TOKENS_PER_MILLION * pricing.input_text
        + cached / TOKENS_PER_MILLION * cached_rate
    )


def _is_audio_modality(modality) -> bool:
    """判斷模態明細是否為音訊(容忍 enum 或字串兩種型別)。"""
    if modality is None:
        return False
    name = getattr(modality, "name", None) or str(modality)
    return "AUDIO" in name.upper()


def _safe_int(value) -> int:
    """把可能為 None 的 token 計數轉成 int(None / 0 → 0)。"""
    return int(value) if value else 0
