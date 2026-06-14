"""
LLM 文字輸出的容錯 JSON 解析 (Pure Functions / DRY)。

當模型以「自由文字」產出 JSON 時（本地 Qwen 素材分析、或 Claude 未走 tool use 的退路），偶爾會夾
markdown 圍欄、前後贅字，或漏一個逗號等小語法錯。本模組集中提供分層容錯解析，讓多處解析端
（導演草稿 ``SchedulingState``、素材分析 ``base_model_manager``）共用同一套韌性、不各自手抄。

與 ``backend/utils/atomic_json`` 的分工：後者針對『檔案』半寫 / 損毀的容錯讀取；本模組針對
『模型文字輸出』的容錯解析，兩者場景不同故各自獨立。

分層策略（由嚴格到寬鬆，命中即回）：
1. 直接 ``json.loads``。
2. 去除 ``` ```json ``` / ``` ``` ``` markdown 圍欄後再 loads。
3. 貪婪擷取第一個 ``{`` 到最後一個 ``}`` 再 loads（去除前後贅字）。
4. ``json-repair`` 修補常見小錯（漏逗號 / 多逗號 / 單引號…）；此為**選用依賴**，未安裝則跳過。
全部失敗回傳 ``default``（不拋例外），由呼叫端決定後續（如導演退回空草稿觸發重生）。
"""
from __future__ import annotations

import json
import re
from typing import Any

# json-repair 為選用修復層：guarded import，未安裝時優雅降級（前三層仍運作，不硬相依）。
try:
    from json_repair import repair_json as _repair_json
except ImportError:  # 未安裝 json-repair：第 4 層自動略過
    _repair_json = None

# markdown 圍欄標記（集中具名，避免 magic string 散落）
_FENCE_JSON = "```json"
_FENCE = "```"
# 擷取第一個 JSON 物件的貪婪樣式（含換行）：去除模型在 JSON 前後夾的贅字
_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _strip_fences(text: str) -> str:
    """去除 ```json … ``` 或 ``` … ``` markdown 圍欄，回傳內層內容（無圍欄則原樣回）。"""
    cleaned = text.strip()
    if _FENCE_JSON in cleaned:
        return cleaned.split(_FENCE_JSON, 1)[-1].split(_FENCE, 1)[0].strip()
    if _FENCE in cleaned:
        parts = cleaned.split(_FENCE)
        return parts[1].strip() if len(parts) > 1 else cleaned
    return cleaned


def parse_json_lenient(text: str, default: Any = None) -> Any:
    """
    容錯解析 LLM 文字輸出的 JSON：由嚴格到寬鬆逐層嘗試，全部失敗回 ``default``（不拋例外）。

    :param text: 模型輸出的原始文字（可能含 markdown 圍欄 / 前後贅字 / 漏逗號等小語法錯）
    :param default: 全部嘗試失敗時的回傳值
    :return: 解析出的物件（dict / list / 純量），或 ``default``
    """
    if not isinstance(text, str) or not text.strip():
        return default

    # 1) 直接 loads（tool use / response_schema 路徑下恆在此命中）
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) 去 markdown 圍欄後 loads
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # 3) 貪婪擷取第一個 JSON 物件後 loads（去前後贅字）
    match = _OBJECT_PATTERN.search(cleaned)
    candidate = match.group(0) if match else cleaned
    if match:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            pass

    # 4) json-repair 修補常見小語法錯（選用依賴；未安裝則 _repair_json 為 None 直接跳過）
    if _repair_json is not None:
        try:
            repaired = _repair_json(candidate, return_objects=True)
            # repair 失敗時可能回空字串 / 空容器；僅在拿到非空結果時採用，否則落回 default
            if repaired not in ("", None, {}, []):
                return repaired
        except Exception:
            pass

    return default
