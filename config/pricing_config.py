"""
Gemini 模型定價表 (Configuration Object Pattern)。

成本統計用：Gemini 回應只有 token 數、無金額欄位，故金額一律由
「token 用量 × 本表單價」推估（依官方公開價目表，非帳單實收）。
``usage_ledger.record_usage`` 是唯一的消費者。

設計重點
--------
- **分模態**：輸入可分文字/影片(同 input_text)與音訊(input_audio)；多數 Gemini
  模型各模態同價，僅少數(如 2.5 Flash)音訊另計，故 input_audio 可為 None(視同文字價)。
- **快取折扣**：命中 context cache 的輸入以 cached_input 計；未開快取時此欄不影響結果。
- 單位一律「USD / 1M tokens」，換算用具名常數 TOKENS_PER_MILLION，禁 magic number。

⚠️ 待確認(見 docs/cost_timing_model_design.md §7)：標註「待確認」的單價需以官方
   價目表核對後再定案；preview 模型 id 與單價可能調整。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 單價以「每 1M tokens」計；計價時除以此常數換算回單顆 token 成本
TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelPricing:
    """單一模型的 token 單價（USD / 1M tokens）。

    :param input_text: 文字/圖片/影片輸入單價（多數 Gemini 各模態同價）。
    :param output: 輸出單價（思考 token 併入此價計算）。
    :param input_audio: 音訊輸入單價；None 代表與 input_text 同價（多數模型如此）。
    :param cached_input: 命中快取的輸入單價（折扣）；None 代表未提供折扣、以 input_text 計。
    """
    input_text: float
    output: float
    input_audio: Optional[float] = None
    cached_input: Optional[float] = None


# TaskMode 用到的 Gemini 模型 → 單價。鍵須與 config.model_config.GEMINI_TASK_MODEL 的值一致。
MODEL_PRICING: dict[str, ModelPricing] = {
    # 1b 深度圖片 / 3 配樂關鍵字（任務輕，取最便宜）
    # ⚠️ 待確認：2.5 Flash-Lite 確切單價（此處先填常見值）
    "gemini-2.5-flash-lite": ModelPricing(input_text=0.10, output=0.40),

    # 1c 影片事件索引 / 2 範本分析（含音訊轉錄；最大成本中心）
    # input/output 已查證；音訊是否另計、快取折扣 ⚠️ 待確認(先視同文字、無快取)
    "gemini-3.1-flash-lite-preview": ModelPricing(input_text=0.25, output=1.50),

    # 4 導演藍圖（純文字推理；premium Flash）
    "gemini-3.5-flash": ModelPricing(input_text=1.50, output=9.00, cached_input=0.15),

    # fallback（舊 default；2.5 Flash 音訊歷史上另計，保守先視同文字 ⚠️ 待確認）
    "gemini-2.5-flash": ModelPricing(input_text=0.30, output=2.50),
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
