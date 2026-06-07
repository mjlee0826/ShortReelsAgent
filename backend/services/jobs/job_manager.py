"""
背景生成 job 的狀態儲存庫 (Singleton + Repository Pattern)。

async job model 下,``POST /api/jobs/generate`` 立即回 job_id 並背景跑工作流;
本模組記錄每個 job 的狀態與最終結果,供 ``GET /api/jobs/{id}`` 取結果、
WebSocket 端點驗證 job 擁有者使用。純 in-memory(單機部署足夠),
以 ``created_at`` + 保留秒數做 lazy 清除,避免已結束 job 無限累積。
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from pydantic import BaseModel, Field

from config.app_config import PROGRESS_JOB_RETENTION_SEC

# job 生命週期的三種狀態(具名常數,避免散落的 magic string)
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE    = "done"
JOB_STATUS_ERROR   = "error"


class Job(BaseModel):
    """單一背景生成 job 的狀態快照(值物件,可直接序列化回 GET 端點)。"""

    job_id: str
    user_id: str
    status: str = JOB_STATUS_RUNNING
    # 成功時帶 run_workflow 的回傳(blueprint / audio_dna / assets_root_url)
    result: Optional[dict] = None
    # 失敗時帶錯誤訊息字串
    error: Optional[str] = None
    # 建立時刻(unix 秒),供保留期清除判斷
    created_at: float = Field(default_factory=time.time)


class JobManager:
    """
    背景 job 狀態的執行緒安全儲存庫 (Singleton)。

    pipeline 在 worker thread 透過端點更新狀態、event loop 上的端點讀取狀態,
    故讀寫全程持鎖。每次新增順手清除「已結束且超過保留期」的 job,避免記憶體無限成長。
    """

    def __init__(self, retention_sec: int = PROGRESS_JOB_RETENTION_SEC):
        """初始化空 job 表與鎖,設定已結束 job 的保留秒數。"""
        self._jobs: dict[str, Job] = {}
        self._retention_sec = retention_sec
        self._lock = threading.Lock()

    def create(self, job_id: str, user_id: str) -> Job:
        """登記一個 running 狀態的新 job 並回傳;新增前順手清除過期 job。"""
        job = Job(job_id=job_id, user_id=user_id)
        with self._lock:
            self._sweep_locked()
            self._jobs[job_id] = job
        return job

    def mark_done(self, job_id: str, result: dict) -> None:
        """將 job 標記為完成並寫入最終結果(job 不存在則靜默忽略)。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JOB_STATUS_DONE
                job.result = result

    def mark_error(self, job_id: str, error: str) -> None:
        """將 job 標記為失敗並寫入錯誤訊息(job 不存在則靜默忽略)。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = JOB_STATUS_ERROR
                job.error = error

    def get(self, job_id: str) -> Optional[Job]:
        """取出 job 狀態快照;不存在回 None。"""
        with self._lock:
            return self._jobs.get(job_id)

    def _sweep_locked(self) -> None:
        """清除已結束(done/error)且超過保留期的 job;必須在持鎖狀態下呼叫。"""
        if self._retention_sec <= 0:
            return
        now = time.time()
        expired = [
            job_id for job_id, job in self._jobs.items()
            if job.status != JOB_STATUS_RUNNING
            and (now - job.created_at) > self._retention_sec
        ]
        for job_id in expired:
            del self._jobs[job_id]


# 模組層級單例:跨請求共享同一份 job 狀態
job_manager = JobManager()
