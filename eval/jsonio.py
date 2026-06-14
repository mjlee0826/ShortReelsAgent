"""pydantic 模型清單與單體的 JSON 讀寫小工具（跨階段共用，避免各處重覆樣板）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

# JSON 縮排寬度（純為了輸出檔可讀；非邏輯門檻）
_JSON_INDENT: int = 2

T = TypeVar("T", bound=BaseModel)


def write_models(path: Path, models: list[T]) -> None:
    """把一串 pydantic 模型寫成 JSON 陣列（UTF-8、保留中文）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [m.model_dump(mode="json") for m in models]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=_JSON_INDENT),
        encoding="utf-8",
    )


def read_models(path: Path, model_cls: type[T]) -> list[T]:
    """讀回 JSON 陣列並驗證成 pydantic 模型清單；檔不存在則回空清單。"""
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    adapter = TypeAdapter(list[model_cls])
    return adapter.validate_python(raw)


def write_model(path: Path, model: BaseModel) -> None:
    """把單一 pydantic 模型寫成 JSON 物件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=_JSON_INDENT),
        encoding="utf-8",
    )
