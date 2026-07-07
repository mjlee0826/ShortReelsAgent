"""
環境變數讀取工具 (DRY)：各 config 模組共用的容錯 env 解析。

原本 ``_read_int_env`` / ``_read_bool_env`` / ``_read_float_env`` 在 model_config /
pipeline_config / ingestion_config 各抄一份、director_config 又手寫多段等價 try/except，
集中於此單一來源。合約一致：未設定或格式錯誤一律回傳 default（壞值不炸啟動）。
只依賴標準庫,任何 config 模組皆可安全 import（無循環依賴風險）。
"""
import os

# bool 解析認可的「真值」字串（小寫比對）
_TRUTHY_STRINGS = {"true", "1", "yes", "on"}


def read_int_env(env_name: str, default: int) -> int:
    """讀取 env var 並轉為 int；未設定或格式錯誤時回傳 default（壞值不炸啟動）。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def read_float_env(env_name: str, default: float) -> float:
    """讀取 env var 並轉為 float；未設定或格式錯誤時回傳 default（壞值不炸啟動）。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def read_bool_env(env_name: str, default: bool) -> bool:
    """讀取 env var 並轉為 bool，接受 true/1/yes/on 等常見字串（其餘一律 False）。"""
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY_STRINGS
