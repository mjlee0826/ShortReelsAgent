"""決定性亂數種子工具。

Python 內建 ``hash()`` 對字串有隨機 salt（跨行程不穩定），故策展亂序命名與 prompt 抽樣
都改用 ``hashlib`` 由字串推導固定種子，確保**可重現**（同一 group_id 每次跑結果一致）。
"""
from __future__ import annotations

import hashlib

# 取 sha256 前 8 bytes 當 64-bit 種子
_SEED_BYTE_WIDTH: int = 8


def stable_seed(text: str) -> int:
    """由字串推導出跨行程穩定的整數種子。

    參數
        text: 任意字串（例如 group_id，或加上用途後綴避免不同用途撞種子）。
    回傳
        可餵給 ``random.Random(seed)`` 的非負整數。
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:_SEED_BYTE_WIDTH], byteorder="big")
