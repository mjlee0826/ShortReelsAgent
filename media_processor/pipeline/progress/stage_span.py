"""stage_span:把單一工作步驟包成 STAGE_START/FINISH(含計時)的 context manager。

讓非 pipeline 的工作(如 music 分支的下載 / 節拍 / 聽寫)也能用一行 ``with`` 對注入的 tracker 發
進度事件,免每處手寫 try/finally;``tracker=None`` 時整段 no-op(退化為純執行,維持舊呼叫端不變)。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator, Optional

from media_processor.pipeline.progress.tracker import ProgressTracker

# 秒 → 毫秒換算(禁 magic number)
_MS_PER_SEC = 1000.0


@contextmanager
def stage_span(
    tracker: Optional[ProgressTracker],
    asset_id: Optional[str],
    stage_name: str,
    payload: Optional[dict] = None,
) -> Iterator[None]:
    """包一個 stage:有 tracker 則發 STAGE_START → (yield) → STAGE_FINISH(含耗時),
    例外時發 STAGE_ERROR 再 re-raise;``tracker`` 為 ``None`` 時 no-op。"""
    if tracker is None:
        yield
        return
    tracker.emit_stage_start(asset_id, stage_name, payload=payload)
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        tracker.emit_stage_error(
            asset_id, stage_name, error=str(exc),
            payload={"duration_ms": (time.perf_counter() - start) * _MS_PER_SEC},
        )
        raise
    else:
        tracker.emit_stage_finish(
            asset_id, stage_name,
            duration_ms=(time.perf_counter() - start) * _MS_PER_SEC,
            payload=payload,
        )
