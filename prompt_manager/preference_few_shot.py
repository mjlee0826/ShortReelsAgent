"""
偏好 few-shot 範例提供者 (偏好資料飛輪 T2)。

惰性讀取人工策展的偏好範例檔(``config/preference_few_shot_examples.json``),格式化成可注入
導演 prompt 的**精簡**文字區塊:聚合心法(``guidance_lines``)＋壓縮版欄位 diff 範例(``examples``)。

三道安全閘(回應「怕 few-shot 沒做好讓 prompt 太長」,見 docs/preference_data_flywheel.md):
1. **預設關**:檔案缺 / 空 / 損毀 → 回空字串,導演 prompt 完全不變(零行為變動)。
2. **只放壓縮 diff**(``path: before → after``),不放整份藍圖。
3. **具名上限硬截長**:筆數 ``MAX_FEWSHOT_EXAMPLES``、每筆欄位數 ``MAX_FIELDS_PER_EXAMPLE``。

結果以 ``lru_cache`` 快取(策展檔屬離線維護,程序生命週期內視為不變;更新策展檔後重啟即生效)。
"""
from __future__ import annotations

import functools
import json
import os
from typing import Optional

from config.director_config import (
    MAX_FEWSHOT_EXAMPLES,
    MAX_FIELDS_PER_EXAMPLE,
    PREFERENCE_FEW_SHOT_EXAMPLES_PATH,
)


def _load() -> Optional[dict]:
    """讀取策展檔;缺檔 / 損毀 / 非 dict 一律回 None(由呼叫端視為「不注入」)。"""
    path = PREFERENCE_FEW_SHOT_EXAMPLES_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Preference FewShot Warning] 讀取偏好範例檔失敗,略過 few-shot: {exc}")
        return None


def _format_example(example: dict) -> Optional[str]:
    """把一筆策展範例格式化成『指令 + 壓縮欄位 diff』;無 changes 則回 None(略過)。"""
    changes = example.get("changes") or []
    if not changes:
        return None
    instruction = (example.get("instruction") or "").strip()
    lines = [f"- 指令：「{instruction}」" if instruction else "- （手動編輯，無指令）"]
    # 每筆只列前 MAX_FIELDS_PER_EXAMPLE 個欄位(壓縮 diff;值用 json 序列化保留型別與引號)
    for change in changes[:MAX_FIELDS_PER_EXAMPLE]:
        path = change.get("path", "?")
        before = json.dumps(change.get("before"), ensure_ascii=False)
        after = json.dumps(change.get("after"), ensure_ascii=False)
        lines.append(f"  - {path}: {before} → {after}")
    return "\n".join(lines)


@functools.lru_cache(maxsize=1)
def build_few_shot_block() -> str:
    """組出可直接拼進導演 prompt 的偏好 few-shot 區塊;無可用內容時回空字串。"""
    data = _load()
    if not data:
        return ""

    sections: list[str] = []

    # 聚合心法:幾行「使用者最常這樣改」
    guidance = [g.strip() for g in (data.get("guidance_lines") or []) if isinstance(g, str) and g.strip()]
    if guidance:
        sections.append("## 使用者常見修正傾向\n" + "\n".join(f"- {g}" for g in guidance))

    # 壓縮 diff 範例:最多 MAX_FEWSHOT_EXAMPLES 筆
    formatted = []
    for example in (data.get("examples") or [])[:MAX_FEWSHOT_EXAMPLES]:
        block = _format_example(example) if isinstance(example, dict) else None
        if block:
            formatted.append(block)
    if formatted:
        sections.append("## 修正範例（指令 → 實際被改的欄位 before → after）\n" + "\n".join(formatted))

    if not sections:
        return ""

    header = (
        "# 偏好範例（few-shot：過往使用者對 AI 排版的修正）\n"
        "排版時順著下列傾向、避免重蹈曾被使用者改掉的決策（這些是壓縮後的欄位變動，非完整藍圖）。\n"
    )
    # 收尾留空行,讓本區塊與後續 instruction 段落乾淨分隔
    return header + "\n".join(sections) + "\n\n"
