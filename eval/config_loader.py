"""階段 0：從 YAML 設定檔讀取並驗證 dataset 規格。

採用 pydantic 做結構驗證（型別、必填、數值約束），錯誤訊息清楚指出問題欄位。
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .logging_setup import get_logger
from .models import DatasetSpec

logger = get_logger(__name__)


def load_dataset_spec(config_path: str | Path) -> DatasetSpec:
    """讀取 YAML 設定檔並驗證成 ``DatasetSpec``。

    參數
        config_path: YAML 設定檔路徑。
    回傳
        驗證通過的 ``DatasetSpec``。
    例外
        FileNotFoundError: 找不到設定檔。
        ValueError: YAML 解析失敗或 schema 驗證失敗（訊息含細節）。
    """
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到設定檔：{path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # YAML 語法錯誤
        raise ValueError(f"設定檔 YAML 解析失敗：{path}\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"設定檔頂層必須是物件（mapping），而非 {type(raw).__name__}：{path}")

    try:
        spec = DatasetSpec.model_validate(raw)
    except ValidationError as exc:  # schema 驗證失敗
        raise ValueError(f"設定檔 schema 驗證失敗：{path}\n{exc}") from exc

    logger.info(
        "已載入 dataset spec：version=%s、共 %d 組、來源=%s",
        spec.dataset_version,
        len(spec.groups),
        [s.value for s in spec.sources],
    )
    return spec
