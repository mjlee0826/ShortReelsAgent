"""
藍圖欄位級 diff (偏好資料飛輪 T1,離線資料處理)。

比較「AI 排版 (before)」與「人改後 (after)」兩份 DirectorBlueprint,逐 clip / text_overlay / bgm
找出被改的欄位,產出機器可讀的 delta。供 ``build_dataset`` 把原始捕捉轉成乾淨偏好配對,並統計
「哪種欄位最常被改」以指出導演弱點(=T2 評測訊號)。

對齊策略:
- **clip 以 ``clip_id`` 配對**(schema 註明不可變);偵測欄位變動、順序變動、增 / 刪。
- **text_overlay 無穩定 id** → 先以文字精確比對求 LCS 當穩定錨點(抓「同字幕、只改樣式 / 位置」),
  錨點外剩餘視為增 / 刪。已知限制:中段插入或改寫文字仍可能誤判成增 + 刪
  (見 docs/preference_data_flywheel.md)。
- **bgm_track 逐欄比對**。
- 一律忽略後端注入 / 非使用者偏好欄位(``track_id`` / ``bpm`` / ``beats`` / ``onsets`` / clip 的
  ``motion`` / ``reason``):這些不是使用者編輯訊號,故不列入比對欄位清單。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# ── 比對欄位清單(具名常數,禁 magic;後端注入欄位刻意不在清單內,自然被忽略)──────────────
# Clip 的純量欄位(巢狀的 color / pip_video 另行展開比對)
_CLIP_SCALAR_FIELDS = (
    "start_at", "end_at", "source_start", "source_end", "playback_rate",
    "object_position", "scale", "transition_in", "clip_volume", "bgm_volume",
)
# ClipColor 的欄位(preset + 可覆寫 primitive)
_COLOR_FIELDS = ("preset", "brightness", "contrast", "saturate", "sepia", "blur", "grayscale")
# PipVideo 的欄位
_PIP_FIELDS = ("clip_id", "source_start", "position")
# TextOverlay 的欄位
_TEXT_FIELDS = (
    "text", "start_at", "end_at", "vertical_position", "horizontal_position",
    "size", "color", "outline", "background", "animation",
)
# BgmTrack 的欄位(刻意不含後端注入的 track_id / bpm / beats / onsets)
_BGM_FIELDS = ("start_at", "source_start", "volume")

# 浮點數比較容差:避免 JSON round-trip 的微小誤差被誤判為「使用者改過」
_FLOAT_EPS = 1e-6

# 字幕增 / 刪摘要截斷長度(只留前幾字辨識,避免 stats 報告過長)
_TEXT_SUMMARY_LEN = 30


@dataclass
class FieldChange:
    """單一欄位的變動:具體路徑 + 前後值。"""

    path: str
    before: Any
    after: Any


@dataclass
class BlueprintDiff:
    """兩份藍圖的完整 diff:欄位級變動 + 結構級(增 / 刪 / 重排)。"""

    changes: list[FieldChange] = field(default_factory=list)   # clip / text / bgm 的欄位變動
    clips_added: list[str] = field(default_factory=list)        # 新增的 clip_id
    clips_removed: list[str] = field(default_factory=list)      # 刪除的 clip_id
    clips_reordered: bool = False                               # 共同片段的相對順序是否改變
    text_added: list[str] = field(default_factory=list)         # 新增字幕(文字摘要)
    text_removed: list[str] = field(default_factory=list)       # 刪除字幕(文字摘要)

    def is_empty(self) -> bool:
        """是否完全無變動(供呼叫端過濾掉「人沒改任何東西」的雜訊配對)。"""
        return not (
            self.changes or self.clips_added or self.clips_removed
            or self.clips_reordered or self.text_added or self.text_removed
        )

    def to_dict(self) -> dict:
        """轉成可序列化 dict(供寫入資料集 JSONL)。"""
        return {
            "changes": [asdict(c) for c in self.changes],
            "clips_added": self.clips_added,
            "clips_removed": self.clips_removed,
            "clips_reordered": self.clips_reordered,
            "text_added": self.text_added,
            "text_removed": self.text_removed,
        }


def _values_differ(a: Any, b: Any) -> bool:
    """判斷兩值是否不同;float 用容差比較,避免序列化誤差誤判為變動。"""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > _FLOAT_EPS
    return a != b


def _pip_summary(pip: Optional[dict]) -> Optional[dict]:
    """把 pip_video 壓成精簡摘要(供「整顆增 / 刪」時記錄前後值)。"""
    if not isinstance(pip, dict):
        return None
    return {k: pip.get(k) for k in _PIP_FIELDS}


def _lcs_text_pairs(before: list[dict], after: list[dict]) -> list[tuple[int, int]]:
    """以文字精確比對求最長共同子序列,回傳保序的配對 (i, j) index 清單。

    用 LCS 找出「文字未變」的字幕當穩定錨點:錨點配對拿來比對樣式 / 位置欄位,
    錨點外的剩餘則由呼叫端視為增 / 刪。
    """
    n, m = len(before), len(after)
    # dp[i][j] = before[:i] 與 after[:j] 的 LCS 長度
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if before[i - 1].get("text", "") == after[j - 1].get("text", ""):
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    # 回溯取出配對
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        if before[i - 1].get("text", "") == after[j - 1].get("text", ""):
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _diff_clips(before: list[dict], after: list[dict]) -> tuple[list[FieldChange], list[str], list[str], bool]:
    """比對片段時間軸:回傳(欄位變動, 新增 id, 刪除 id, 是否重排)。"""
    changes: list[FieldChange] = []
    before_by_id = {c.get("clip_id"): c for c in before}
    after_by_id = {c.get("clip_id"): c for c in after}

    added = [c.get("clip_id") for c in after if c.get("clip_id") not in before_by_id]
    removed = [c.get("clip_id") for c in before if c.get("clip_id") not in after_by_id]

    # 共同片段的相對順序是否改變(只看兩邊都有的 id,保留各自順序後比對)
    common_before = [c.get("clip_id") for c in before if c.get("clip_id") in after_by_id]
    common_after = [c.get("clip_id") for c in after if c.get("clip_id") in before_by_id]
    reordered = common_before != common_after

    # 共同片段逐欄比對(以 before 的順序走訪)
    for cid in common_before:
        b, a = before_by_id[cid], after_by_id[cid]
        for f in _CLIP_SCALAR_FIELDS:
            if _values_differ(b.get(f), a.get(f)):
                changes.append(FieldChange(f"clip[{cid}].{f}", b.get(f), a.get(f)))
        # 調色(巢狀 dict;留空 primitive 視為 None)
        bc, ac = (b.get("color") or {}), (a.get("color") or {})
        for f in _COLOR_FIELDS:
            if _values_differ(bc.get(f), ac.get(f)):
                changes.append(FieldChange(f"clip[{cid}].color.{f}", bc.get(f), ac.get(f)))
        # 畫中畫(可能整顆為 None)
        bp, ap = b.get("pip_video"), a.get("pip_video")
        if bool(bp) != bool(ap):
            changes.append(FieldChange(f"clip[{cid}].pip_video", _pip_summary(bp), _pip_summary(ap)))
        elif bp and ap:
            for f in _PIP_FIELDS:
                if _values_differ(bp.get(f), ap.get(f)):
                    changes.append(FieldChange(f"clip[{cid}].pip_video.{f}", bp.get(f), ap.get(f)))
    return changes, added, removed, reordered


def _diff_text_overlays(before: list[dict], after: list[dict]) -> tuple[list[FieldChange], list[str], list[str]]:
    """比對字幕軌:回傳(欄位變動, 新增摘要, 刪除摘要)。"""
    changes: list[FieldChange] = []
    pairs = _lcs_text_pairs(before, after)
    matched_before = {i for i, _ in pairs}
    matched_after = {j for _, j in pairs}

    # 配對成功(文字相同)者:比對樣式 / 位置欄位
    for _i, j in pairs:
        b, a = before[_i], after[j]
        for f in _TEXT_FIELDS:
            if _values_differ(b.get(f), a.get(f)):
                changes.append(FieldChange(f"text_overlay[{j}].{f}", b.get(f), a.get(f)))

    removed = [
        (before[i].get("text", "") or "")[:_TEXT_SUMMARY_LEN]
        for i in range(len(before)) if i not in matched_before
    ]
    added = [
        (after[j].get("text", "") or "")[:_TEXT_SUMMARY_LEN]
        for j in range(len(after)) if j not in matched_after
    ]
    return changes, added, removed


def diff_blueprint(before: Optional[dict], after: Optional[dict]) -> BlueprintDiff:
    """比對兩份藍圖,回傳完整 :class:`BlueprintDiff`(任一為 None 時當空藍圖處理)。"""
    before = before or {}
    after = after or {}

    result = BlueprintDiff()

    # 全局配樂
    bb, ba = (before.get("bgm_track") or {}), (after.get("bgm_track") or {})
    for f in _BGM_FIELDS:
        if _values_differ(bb.get(f), ba.get(f)):
            result.changes.append(FieldChange(f"bgm_track.{f}", bb.get(f), ba.get(f)))

    # 片段時間軸
    c_changes, c_added, c_removed, reordered = _diff_clips(
        before.get("timeline") or [], after.get("timeline") or []
    )
    result.changes.extend(c_changes)
    result.clips_added = c_added
    result.clips_removed = c_removed
    result.clips_reordered = reordered

    # 字幕軌
    t_changes, t_added, t_removed = _diff_text_overlays(
        before.get("text_overlays") or [], after.get("text_overlays") or []
    )
    result.changes.extend(t_changes)
    result.text_added = t_added
    result.text_removed = t_removed

    return result


def normalize_path(path: str) -> str:
    """把含 id / index 的具體路徑正規化成統計用的通用欄位鍵(如 ``clip.object_position``)。

    例:``clip[raw/a.mp4].object_position`` → ``clip.object_position``;
        ``text_overlay[2].vertical_position`` → ``text_overlay.vertical_position``;
        ``bgm_track.volume`` 維持原樣。
    """
    for prefix, generic in (("clip[", "clip"), ("text_overlay[", "text_overlay")):
        if path.startswith(prefix):
            idx = path.find("].")
            if idx != -1:
                return f"{generic}.{path[idx + 2:]}"
    return path
