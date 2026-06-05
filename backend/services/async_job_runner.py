"""
背景生成 job 啟動器 (Template Method + Singleton)。

把 async job model 的共用骨架抽成單一入口:建 job → 建帶 job_id 的 ProgressTracker(訂閱 WS
Observer)→ 背景執行緒跑工作 → 成功 / 失敗寫回 JobManager 並發 JOB_FINISHED / JOB_ERROR 終端事件
→ 收尾 WS 連線。完整生成(``run_workflow``)與 Phase 1 重分析共用同一套生命週期,只差中間那段
``work_fn``。
"""
from __future__ import annotations

import asyncio
import traceback
import uuid
from typing import Callable

from backend.api.progress import progress_hub, ws_progress_observer
from backend.services.job_manager import job_manager
from media_processor.pipeline.progress import ProgressTracker

# work_fn:在 worker thread 內執行實際工作(收到帶 job_id 的 tracker),回傳要落地的結果 dict
WorkFn = Callable[[ProgressTracker], dict]


class AsyncJobRunner:
    """建立背景 job 並把進度經 tracker 串到 WebSocket 的啟動器。"""

    def __init__(self) -> None:
        """保存背景任務強參照,避免 asyncio.Task 執行中被 GC 提早回收。"""
        self._tasks: set[asyncio.Task] = set()

    def launch(self, user_id: str, work_fn: WorkFn) -> str:
        """
        建立一個背景 job,立即回 job_id(不等工作跑完)。

        前端據此開 ``WS /ws/progress/{job_id}`` 看即時進度、用 ``GET /api/jobs/{job_id}`` 取最終結果。
        須在 event loop 的 coroutine 內呼叫(內部 ``ensure_loop`` 會捕捉當前 loop 供 worker thread 排程)。
        """
        job_id = uuid.uuid4().hex
        job_manager.create(job_id, user_id)
        # tracker 帶此 job_id,訂閱 WebSocket Observer;事件依 job_id 分流到對應連線
        tracker = ProgressTracker(job_id=job_id)
        tracker.subscribe(ws_progress_observer)
        # 先在此 event loop 執行緒捕捉 loop,讓 worker thread 的事件能排回本 loop
        progress_hub.ensure_loop()
        task = asyncio.create_task(self._run(job_id, tracker, work_fn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job_id

    async def _run(self, job_id: str, tracker: ProgressTracker, work_fn: WorkFn) -> None:
        """背景跑 work_fn:結束時把結果 / 錯誤寫回 JobManager、發終端事件,並收尾 WS 連線。"""
        try:
            result = await asyncio.to_thread(work_fn, tracker)
            job_manager.mark_done(job_id, result)
            tracker.emit_job_finished(payload={"result": result})
        except Exception as exc:  # noqa: BLE001 - 背景工作任何例外都需轉成 job 錯誤,不可逸出
            print("\n❌ [背景 job 發生錯誤] 詳細報錯資訊如下：")
            traceback.print_exc()
            job_manager.mark_error(job_id, str(exc))
            tracker.emit_job_error(error=str(exc))
        finally:
            # 推哨兵讓 WS 迴圈優雅收尾,並排程清除該 job 的 replay buffer
            progress_hub.finish(job_id)


# 模組層級單例:跨請求共享同一個啟動器(背景任務集合需長存)
async_job_runner = AsyncJobRunner()
