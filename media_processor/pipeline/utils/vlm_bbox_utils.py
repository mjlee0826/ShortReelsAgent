"""
vlm_bbox_utils:把 VLM(Qwen / Gemini)輸出的原始主體框安全轉成正規化 ``SubjectBbox``。

兩家模型的座標慣例不同(見 ``parse_qwen_bbox`` / ``parse_gemini_bbox`` 各自的 docstring),
本模組統一吃進「原始 4 元素座標」,依來源指定的『軸序 + 尺度』換算成 0–100 百分比的
``SubjectBbox``,並做防呆:非 4 數、退化(面積過小)、慣例不符等情況一律回 ``None``,
讓呼叫端退回既有 CV(U²-Net / saliency)路徑——確保接入 VLM 框「零退步」。

座標換算邏輯集中於此(DRY):Simple 影像 / 影片在 Assembly、Complex 影片在 EventBbox 共用同一入口。
"""
from __future__ import annotations

from typing import Optional, Sequence

from media_processor.models import SubjectBbox

# ── 軸序:VLM 原始 4 元素的排列方式 ───────────────────────────────────────────
_ORDER_XYXY = "xyxy"  # [x1, y1, x2, y2](Qwen 原生 / prompt 指定)
_ORDER_YXYX = "yxyx"  # [ymin, xmin, ymax, xmax](Gemini 原生:y 在前)

# ── 各家模型的正規化尺度(prompt 一併要求同一尺度;不符會被防呆退 None)──────────
_QWEN_SCALE = 1000.0    # Qwen:prompt 指定正規化到 0–1000
_GEMINI_SCALE = 1000.0  # Gemini:原生輸出 0–1000

# ── 百分比上下界與退化判定 ────────────────────────────────────────────────────
_PCT_MIN = 0.0
_PCT_MAX = 100.0
_PCT_NDIGITS = 1
# 換算後寬或高小於此百分比視為無效框:可同時擋掉「模型亂吐」與「座標慣例不符被縮成極小框」
_MIN_SIDE_PCT = 1.0
# 找不到主體時的全畫面安全框(x1,y1,x2,y2):代表「不裁切、任意位置皆可」,移除 U²-Net 後的最終 fallback
_FULL_FRAME = (0.0, 0.0, 100.0, 100.0)


def full_frame_bbox() -> SubjectBbox:
    """主體框最終 fallback:全畫面安全框 (0,0,100,100)。VLM 未給有效框時用,語意為「整幅皆主體」。"""
    x1, y1, x2, y2 = _FULL_FRAME
    return SubjectBbox(x1=x1, y1=y1, x2=x2, y2=y2)


def parse_qwen_bbox(raw) -> Optional[SubjectBbox]:
    """
    解析 Qwen 主體框:慣例為 ``[x1, y1, x2, y2]``、正規化 0–1000(由 prompt 指定)。

    無效 / 退化 / 慣例不符回 ``None``,呼叫端據此退回臉部 / U²-Net saliency 既有路徑。
    """
    return parse_vlm_bbox(raw, order=_ORDER_XYXY, scale=_QWEN_SCALE)


def parse_gemini_bbox(raw) -> Optional[SubjectBbox]:
    """
    解析 Gemini 主體框:原生慣例為 ``[ymin, xmin, ymax, xmax]``、0–1000(**y 在前**)。

    無效 / 退化回 ``None``,呼叫端據此退回 key_timestamp 精確幀的 CV saliency 既有路徑。
    """
    return parse_vlm_bbox(raw, order=_ORDER_YXYX, scale=_GEMINI_SCALE)


def parse_vlm_bbox(raw, *, order: str, scale: float) -> Optional[SubjectBbox]:
    """
    把 VLM 原始 bbox(4 數序列)依 ``order`` / ``scale`` 換算成 0–100 的 ``SubjectBbox``。

    流程:取 4 數 → 依軸序還原 (x1,y1,x2,y2) → 除尺度轉百分比 → 保證左上<右下 → 夾範圍 →
    退化框視為無效。任一步失敗回 ``None``(交由呼叫端 fallback,絕不丟出例外)。
    """
    coords = _coerce_four_numbers(raw)
    if coords is None:
        return None

    a, b, c, d = coords
    # 依軸序還原成 (x1,y1,x2,y2),此時仍是模型原始尺度
    if order == _ORDER_YXYX:
        x1_raw, y1_raw, x2_raw, y2_raw = b, a, d, c
    else:  # 預設 xyxy
        x1_raw, y1_raw, x2_raw, y2_raw = a, b, c, d

    # 原始尺度 → 百分比
    x1, y1, x2, y2 = (value / scale * _PCT_MAX for value in (x1_raw, y1_raw, x2_raw, y2_raw))
    # 模型偶爾把左上/右下顛倒,排序保證 x1<x2、y1<y2
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    # 夾在合法百分比範圍(防超界座標)
    x1, y1, x2, y2 = (_clamp_percent(value) for value in (x1, y1, x2, y2))

    # 退化框(常見於座標慣例不符:像素值被當 0–1000 除而縮成極小框)→ 視為無效
    if (x2 - x1) < _MIN_SIDE_PCT or (y2 - y1) < _MIN_SIDE_PCT:
        return None

    return SubjectBbox(
        x1=round(x1, _PCT_NDIGITS),
        y1=round(y1, _PCT_NDIGITS),
        x2=round(x2, _PCT_NDIGITS),
        y2=round(y2, _PCT_NDIGITS),
    )


def _coerce_four_numbers(raw) -> Optional[tuple]:
    """raw 必須是長度 4、可全部轉成 float 的序列(list/tuple);否則回 None。"""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 4:
        return None
    try:
        return tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return None


def _clamp_percent(value: float) -> float:
    """夾在 [0, 100] 百分比範圍。"""
    return max(_PCT_MIN, min(_PCT_MAX, value))
