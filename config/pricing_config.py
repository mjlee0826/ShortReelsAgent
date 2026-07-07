"""
LLM 模型定價表 (Configuration Object Pattern)。

成本統計用：API 回應只有 token 數、無金額欄位，故金額一律由
「token 用量 × 本表單價」推估（依官方公開價目表，非帳單實收）。
``usage_ledger`` 是唯一的消費者。

設計重點
--------
- **分模態**：輸入可分文字/影片(同 input_text)與音訊(input_audio)；多數 Gemini
  模型各模態同價，僅少數(如 2.5 Flash)音訊另計，故 input_audio 可為 None(視同文字價)。
- **快取**：命中快取的輸入以 cached_input 計；Anthropic 另有「快取寫入」費
  (cache_write_input，5 分鐘 TTL 為輸入價 1.25×)，agentic loop 每輪都在寫入遞增前綴快取，
  漏算會系統性低估 Phase 4 成本。
- **階梯價**：Gemini 3.1 Pro 對 >200k tokens 的 prompt 採高費率(輸入/輸出/快取皆換檔)，
  以 ``tier_threshold_tokens`` + ``*_over`` 欄位建模；``rates_for_prompt`` 依 prompt 大小
  回傳生效費率，呼叫端(usage_ledger)無需自帶階梯邏輯。
- 單位一律「USD / 1M tokens」，換算用具名常數 TOKENS_PER_MILLION，禁 magic number。

價格查證：2026-07-06 對照官方價目表
(https://ai.google.dev/gemini-api/docs/pricing 與 Anthropic 官方價)。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

# 單價以「每 1M tokens」計；計價時除以此常數換算回單顆 token 成本
TOKENS_PER_MILLION = 1_000_000

# Anthropic 快取寫入的預設倍率（5 分鐘 TTL = 輸入價 1.25×）；模型未明列 cache_write_input 時的後備
ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class ModelPricing:
    """單一模型的 token 單價（USD / 1M tokens）。

    :param input_text: 文字/圖片/影片輸入單價（多數 Gemini 各模態同價）。
    :param output: 輸出單價（思考 token 併入此價計算）。
    :param input_audio: 音訊輸入單價；None 代表與 input_text 同價（多數模型如此）。
    :param cached_input: 命中快取的輸入單價（讀取折扣）；None 代表未提供折扣、以 input_text 計。
    :param cache_write_input: 寫入快取的輸入單價（Anthropic 5m TTL = 1.25× 輸入價）；
        None 時計價端以 ``input_text × ANTHROPIC_CACHE_WRITE_MULTIPLIER`` 後備。
    :param tier_threshold_tokens: 階梯價門檻（prompt tokens）；None = 無階梯。
    :param input_text_over / output_over / cached_input_over: 超過門檻後的高檔費率
        （None 沿用基礎費率）。
    """
    input_text: float
    output: float
    input_audio: Optional[float] = None
    cached_input: Optional[float] = None
    cache_write_input: Optional[float] = None
    tier_threshold_tokens: Optional[int] = None
    input_text_over: Optional[float] = None
    output_over: Optional[float] = None
    cached_input_over: Optional[float] = None

    def rates_for_prompt(self, prompt_tokens: int) -> "ModelPricing":
        """依 prompt 大小回傳生效費率：超過階梯門檻時把基礎費率換成 ``*_over`` 高檔費率。

        無階梯（tier_threshold_tokens 為 None）或未超標時回自身；超標時回一份把
        input/output/cached 換成高檔值的副本，呼叫端後續計價邏輯完全不變。
        """
        if self.tier_threshold_tokens is None or prompt_tokens <= self.tier_threshold_tokens:
            return self
        return replace(
            self,
            input_text=self.input_text_over if self.input_text_over is not None else self.input_text,
            output=self.output_over if self.output_over is not None else self.output,
            cached_input=self.cached_input_over if self.cached_input_over is not None else self.cached_input,
        )


# TaskMode 用到的模型 → 單價。鍵須與 config.model_config 的模型 id 一致。
MODEL_PRICING: dict[str, ModelPricing] = {
    # 1b 深度圖片分析 / 1c 影片事件索引 / 3 配樂關鍵字 / 4-0 選角（2026-07-06 官方查證）
    "gemini-2.5-flash": ModelPricing(
        input_text=0.30, output=2.50, input_audio=1.00, cached_input=0.03,
    ),
    # 後備輕量模型（2026-07-06 官方查證）
    "gemini-2.5-flash-lite": ModelPricing(
        input_text=0.10, output=0.40, input_audio=0.30, cached_input=0.01,
    ),

    # 曾 A/B 的 preview 型號——目前未被任何 task 採用，僅留供 env 覆寫再試（未再查證）
    "gemini-3.1-flash-lite-preview": ModelPricing(input_text=0.25, output=1.50),

    # 曾 A/B 的 premium Flash（2026-07-06 官方查證）——目前未採用（實測未優於 3.1 Pro）
    "gemini-3.5-flash": ModelPricing(input_text=1.50, output=9.00, cached_input=0.15),

    # 4 導演藍圖（DIRECTOR_PROVIDER=gemini 時）。>200k prompt 有階梯價（2026-07-06 官方查證）：
    # 輸入 $2→$4、輸出 $12→$18、快取 $0.20→$0.40，由 rates_for_prompt 依 prompt 大小換檔。
    "gemini-3.1-pro-preview": ModelPricing(
        input_text=2.00, output=12.00, cached_input=0.20,
        tier_threshold_tokens=200_000,
        input_text_over=4.00, output_over=18.00, cached_input_over=0.40,
    ),

    # 4 導演藍圖（Claude 預設 provider；2026-07-06 官方查證）。
    # cache_write_input = 5m TTL 寫入費（1.25×）；thinking token 由 Anthropic 計入 output、以 output 價計。
    "claude-opus-4-8": ModelPricing(
        input_text=5.00, output=25.00, cached_input=0.50, cache_write_input=6.25,
    ),
    "claude-sonnet-4-6": ModelPricing(
        input_text=3.00, output=15.00, cached_input=0.30, cache_write_input=3.75,
    ),
    # 配樂 brief 等輕量結構化任務（2026-07-06 官方查證）
    "claude-haiku-4-5": ModelPricing(
        input_text=1.00, output=5.00, cached_input=0.10, cache_write_input=1.25,
    ),
}

# 查無對應模型時的後備單價（與 GEMINI_FALLBACK_MODEL 對齊，避免 KeyError）
_FALLBACK_PRICING_MODEL = "gemini-2.5-flash"


def get_pricing(model: str) -> ModelPricing:
    """取某模型的單價；查無時退回後備模型單價（保證有值，計價不致中斷）。"""
    pricing = MODEL_PRICING.get(model)
    if pricing is not None:
        return pricing
    # 後備模型本身必存在於表中；若連它都缺(理應不會)則給一個保守預設避免崩潰
    return MODEL_PRICING.get(_FALLBACK_PRICING_MODEL, ModelPricing(input_text=0.30, output=2.50))
