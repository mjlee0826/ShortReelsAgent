"""讓套件可用 ``python -m eval`` 執行。"""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
