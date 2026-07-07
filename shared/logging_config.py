"""
全案統一的 logging 設定 (Configuration Object Pattern)。

print → logging 轉換後的單一設定入口：各模組以 ``logging.getLogger(__name__)`` 取 logger，
由**進入點**（backend/main.py、CLI 工具）呼叫一次 :func:`setup_logging` 掛 handler。
好處：時間戳 + 等級 + 模組名自動帶上（多 worker 併發下可歸因）、LOG_LEVEL 可調（排查時開 DEBUG、
生產壓 WARNING）、日後要接檔案 / 集中式收集只改這一處。

訊息文字維持既有中文與 emoji 慣例不動——只換傳輸層，不改內容。
"""
import logging
import os

# 統一格式：時間 + 等級縮寫 + 模組名 + 訊息（模組名讓多 worker 併發輸出可歸因）
_LOG_FORMAT = "%(asctime)s %(levelname).1s [%(name)s] %(message)s"
_LOG_DATEFMT = "%H:%M:%S"
# 預設等級（env LOG_LEVEL 覆寫：DEBUG / INFO / WARNING / ERROR）
_DEFAULT_LEVEL = "INFO"


def setup_logging(level: str | None = None) -> None:
    """
    設定 root logger（進入點呼叫一次；重複呼叫為 no-op，沿用 basicConfig 語意）。

    :param level: 明示等級字串；None 時讀 env ``LOG_LEVEL``（預設 INFO）。壞值回退預設。
    """
    raw = (level or os.environ.get("LOG_LEVEL", _DEFAULT_LEVEL)).strip().upper()
    resolved = getattr(logging, raw, None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(level=resolved, format=_LOG_FORMAT, datefmt=_LOG_DATEFMT)
