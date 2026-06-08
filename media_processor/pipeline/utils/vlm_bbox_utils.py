"""
vlm_bbox_utils:把 VLM(Qwen / Gemini)輸出的原始主體框安全轉成正規化 ``SubjectBbox``。

兩家模型的座標慣例不同(Qwen ``[x1,y1,x2,y2]`` / Gemini ``[ymin,xmin,ymax,xmax]``,皆 0–1000;
見 ``_ORDER_*`` / ``_*_SCALE`` 常數),本模組統一吃進「原始 4 元素座標」,依來源指定的『軸序 + 尺度』
換算成 0–100 百分比的 ``SubjectBbox``,並做防呆:非 4 數、退化(面積過小)、慣例不符等情況一律回
``None``,讓呼叫端退回臉部 / 全畫面安全框——確保接入 VLM 框「零退步」。

**top-N 候選選框**:為緩解「只逼模型一次定案而選錯主體」(mode A),prompt 改要求模型
依信心排序輸出前幾名候選主體。``parse_*_candidates`` 把候選清單逐筆換算成
``SubjectCandidate``,``select_best_candidate`` 再依「信心 + 9:16 可裁性」挑出最佳框——
信心為主、可裁性為輔,讓「信心略低但能完整入直式框」的主體有機會勝出。

座標換算邏輯集中於此(DRY):Simple 影像 / 影片在 Assembly、Complex 影片逐 event 共用同一入口。
"""
from __future__ import annotations

from typing import Optional, Sequence

from config.media_processor_config import (
    CROP_NOT_RECOMMENDED_THRESHOLD,
    CROP_PARTIAL_THRESHOLD,
    SUBJECT_CANDIDATE_DEFAULT_CONFIDENCE,
    SUBJECT_CANDIDATE_TOP_N,
    SUBJECT_SELECT_CONFIDENCE_WEIGHT,
    SUBJECT_SELECT_CROP_FIT_WEIGHT,
)
from media_processor.models import SubjectBbox, SubjectCandidate

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
# aspect_ratio ≤ 此值視為直式 / 方形:已是 9:16 友善,任何框都可完整保留(可裁性恆為滿分)
_SQUARE_ASPECT = 1.0
# 9:16 可裁性分數上下界(線性映射至 [_CROP_FIT_MIN, _CROP_FIT_MAX])
_CROP_FIT_MIN = 0.0
_CROP_FIT_MAX = 1.0


def full_frame_bbox() -> SubjectBbox:
    """主體框最終 fallback:全畫面安全框 (0,0,100,100)。VLM 未給有效框時用,語意為「整幅皆主體」。"""
    x1, y1, x2, y2 = _FULL_FRAME
    return SubjectBbox(x1=x1, y1=y1, x2=x2, y2=y2)


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


# ── top-N 候選解析與聰明選框 ─────────────────────────────────────────────────


def parse_qwen_candidates(raw) -> list[SubjectCandidate]:
    """解析 Qwen 候選主體清單(bbox 慣例 ``[x1,y1,x2,y2]``、0–1000),依信心遞減排序。"""
    return parse_vlm_candidates(raw, order=_ORDER_XYXY, scale=_QWEN_SCALE)


def parse_gemini_candidates(raw) -> list[SubjectCandidate]:
    """解析 Gemini 候選主體清單(bbox 慣例 ``[ymin,xmin,ymax,xmax]``、0–1000),依信心遞減排序。"""
    return parse_vlm_candidates(raw, order=_ORDER_YXYX, scale=_GEMINI_SCALE)


def parse_vlm_candidates(raw, *, order: str, scale: float) -> list[SubjectCandidate]:
    """
    把 VLM 候選主體清單轉成依信心遞減排序的 ``SubjectCandidate`` 清單。

    raw 預期為 ``[{"bbox": [...], "label": str, "confidence": float}, ...]``;逐筆:
    bbox 經 ``parse_vlm_bbox`` 防呆換算(無效即丟棄該候選),label / confidence 缺值給安全預設。
    相容退化輸入:raw 為單一 4 數框、或元素直接是 4 數框時,皆視為單一候選(向後相容舊 ``subject_bbox``)。
    最後依 confidence 遞減排序並截斷至 ``SUBJECT_CANDIDATE_TOP_N``,任何格式問題都安全略過、回空清單交由呼叫端 fallback。
    """
    candidates: list[SubjectCandidate] = []
    for item in _coerce_candidate_items(raw):
        bbox_raw, label, confidence = _split_candidate_item(item)
        bbox = parse_vlm_bbox(bbox_raw, order=order, scale=scale)
        if bbox is None:
            continue
        candidates.append(SubjectCandidate(bbox=bbox, label=label, confidence=confidence))
    # 信心高者排前;只採信前 N 名,避免模型亂吐長尾候選干擾選框
    candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return candidates[:SUBJECT_CANDIDATE_TOP_N]


def select_best_candidate(
    candidates: Sequence[SubjectCandidate], aspect_ratio: float
) -> Optional[SubjectBbox]:
    """
    從候選清單挑最適合 9:16 直式輸出的主體框。

    評分 = 信心 * ``CONFIDENCE_WEIGHT`` + 9:16 可裁性 * ``CROP_FIT_WEIGHT``:信心為主、可裁性為輔,
    讓「信心略低但能完整框入直式」的主體有機會勝出(緩解模型誤選寬幅 / 次要主體)。
    候選為空回 ``None``,交由呼叫端退臉部 / 全畫面安全框。
    """
    if not candidates:
        return None
    best = max(candidates, key=lambda candidate: _candidate_score(candidate, aspect_ratio))
    return best.bbox


def _candidate_score(candidate: SubjectCandidate, aspect_ratio: float) -> float:
    """單一候選的綜合分:信心加權 + 9:16 可裁性加權。"""
    crop_fit = _crop_fitness(candidate.bbox, aspect_ratio)
    return (
        SUBJECT_SELECT_CONFIDENCE_WEIGHT * candidate.confidence
        + SUBJECT_SELECT_CROP_FIT_WEIGHT * crop_fit
    )


def _crop_fitness(bbox: SubjectBbox, aspect_ratio: float) -> float:
    """
    回傳框在 9:16 直式裁切下的「可完整保留度」(0–1)。

    直式 / 方形素材(已是 9:16 友善)恆為滿分;橫式素材則看框寬:未超過 partial 邊界 → 滿分,
    超過 not_recommended → 0,之間線性遞減。對應 ``_compute_crop_feasibility`` 的同一組門檻。
    """
    if aspect_ratio <= _SQUARE_ASPECT:
        return _CROP_FIT_MAX
    width = bbox.x2 - bbox.x1
    if width <= CROP_PARTIAL_THRESHOLD:
        return _CROP_FIT_MAX
    if width >= CROP_NOT_RECOMMENDED_THRESHOLD:
        return _CROP_FIT_MIN
    span = CROP_NOT_RECOMMENDED_THRESHOLD - CROP_PARTIAL_THRESHOLD
    return (CROP_NOT_RECOMMENDED_THRESHOLD - width) / span


def _coerce_candidate_items(raw) -> list:
    """把 raw 正規化成「候選元素清單」:單一 dict / 單一 4 數框各視為一筆;非序列回空清單。"""
    if raw is None:
        return []
    # 模型只回單一候選物件
    if isinstance(raw, dict):
        return [raw]
    # 退化:整個 raw 就是一個 4 數框(向後相容舊 subject_bbox)→ 當成唯一候選
    if _coerce_four_numbers(raw) is not None:
        return [raw]
    # 正常:候選清單(逐元素可能是 dict 或 4 數框)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return list(raw)
    return []


def _split_candidate_item(item) -> tuple:
    """從單筆候選取出 (bbox 原始值, label, confidence);非 dict 退化形視為純 bbox。"""
    if isinstance(item, dict):
        # 相容 "bbox" 與舊鍵 "subject_bbox"
        bbox_raw = item.get("bbox", item.get("subject_bbox"))
        label = str(item.get("label", "")).strip()
        confidence = _coerce_confidence(item.get("confidence"))
        return bbox_raw, label, confidence
    # 元素直接是 4 數框 → 無 label、給中性信心
    return item, "", SUBJECT_CANDIDATE_DEFAULT_CONFIDENCE


def _coerce_confidence(value) -> float:
    """信心轉 float 並夾在 [0,1];缺值 / 非數值回中性預設(不被當 0 永遠墊底)。"""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return SUBJECT_CANDIDATE_DEFAULT_CONFIDENCE
    return max(0.0, min(1.0, confidence))


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
