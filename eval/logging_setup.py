"""logging 設定（取代專案慣用的 print，提供分級、模組前綴的清楚 log）。

對外只暴露 ``configure_logging`` 與 ``get_logger``：各模組以 ``get_logger(__name__)`` 取得
帶 ``eval.<module>`` 前綴的 logger，輸出統一格式（見 constants.LOG_FORMAT）。
"""
from __future__ import annotations

import logging
import sys

from .constants import LOG_DATEFMT, LOG_FORMAT

# 套件根 logger 名稱；所有子 logger 皆掛在其下
_ROOT_LOGGER_NAME: str = "eval"


def configure_logging(*, verbose: bool = False) -> None:
    """設定套件根 logger（冪等：重複呼叫不會重覆掛 handler）。

    參數
        verbose: True 時輸出 DEBUG 級別，否則 INFO。
    """
    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    if logger.handlers:
        # 已設定過就只更新層級，不重複加 handler（避免重複輸出）
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATEFMT))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    # 不向 root logger 傳播，避免與其他函式庫的 handler 重複輸出
    logger.propagate = False


def get_logger(module_name: str) -> logging.Logger:
    """取得帶 ``eval.`` 前綴的子 logger。

    參數
        module_name: 通常傳 ``__name__``；會被正規化成 ``eval.<尾段>``。
    """
    # 把 "eval.sources.pexels" 之類的 __name__ 收斂成 eval 子 logger
    leaf = module_name.split(".")[-1]
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{leaf}")
