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
from typing import Callable, Optional

from backend.services.jobs.job_manager import job_manager
from backend.services.jobs.progress_hub import progress_hub, ws_progress_observer
from media_processor.pipeline.progress import ProgressTracker

# work_fn:在 worker thread 內執行實際工作(收到帶 job_id 的 tracker),回傳要落地的結果 dict
WorkFn = Callable[[ProgressTracker], dict]
# on_job_created:job_id 一產生(work 尚未開跑)即回呼,供呼叫端把 job_id 曝露給前端(如落地 meta)
JobCreatedHook = Callable[[str], None]


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

    def run_tracked_sync(
        self, user_id: str, work_fn: WorkFn,
        on_job_created: Optional[JobCreatedHook] = None,
    ) -> dict:
        """
        在「目前的 worker thread」內同步跑一個 tracked job(建 job_id、tracker、發 WS 事件),阻塞至完成。

        供雲端同步等「已在 worker thread、且呼叫端需等結果」的場景使用,與背景 ``launch`` 共用同一套
        job 生命週期(Template Method):建 job → 建帶 job_id 的 tracker(訂閱 WS Observer)→ 跑 work →
        成功 / 失敗寫回 JobManager 並發 JOB_FINISHED / JOB_ERROR 終端事件 → 收尾 WS 連線。差別僅在此版本
        同步阻塞、不自建 asyncio.Task,故收尾改用 ``finish_threadsafe``(從 worker thread 排回 loop)。

        ``on_job_created`` 在 job_id 產生、work 開跑「之前」回呼,讓呼叫端先把 job_id 曝露給前端訂閱。
        失敗時 raise(交回呼叫端決定後續,例如雲端同步據此標 failed)。回傳含 job_id 與 work 結果的 dict。

        前置條件:app 啟動時已 ``progress_hub.ensure_loop()``(見 backend/main.py lifespan),
        否則 worker thread 發的事件無 loop 可排,只進 replay buffer(待 WS attach 時補播)。
        """
        job_id = uuid.uuid4().hex
        job_manager.create(job_id, user_id)
        # tracker 帶此 job_id,訂閱 WebSocket Observer;事件依 job_id 分流到對應連線
        tracker = ProgressTracker(job_id=job_id)
        tracker.subscribe(ws_progress_observer)
        if on_job_created is not None:
            on_job_created(job_id)  # 先曝露 job_id(如落地 meta),讓前端能在 work 跑的同時訂閱
        try:
            result = work_fn(tracker)
            job_manager.mark_done(job_id, result)
            tracker.emit_job_finished(payload={"result": result})
            return {"job_id": job_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - 轉成 job 錯誤並發終端事件後,仍 raise 交回呼叫端
            print("\n❌ [背景 job 發生錯誤] 詳細報錯資訊如下：")
            traceback.print_exc()
            job_manager.mark_error(job_id, str(exc))
            tracker.emit_job_error(error=str(exc))
            raise
        finally:
            # 在 worker thread 收尾:推哨兵讓 WS 迴圈優雅收尾,並排程清除 replay buffer(經 loop 排回)
            progress_hub.finish_threadsafe(job_id)

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
