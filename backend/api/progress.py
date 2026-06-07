"""
進度推播 WebSocket 端點 (Observer Pattern 的對外出口)。

把 ``ProgressHub``(連線中樞,見 ``backend.services.jobs.progress_hub``)的事件流經
``/ws/progress/{job_id}`` 對外串流:先送 replay(補播開頭事件)、再串流即時事件,直到 job 結束
(哨兵)或斷線。Hub / Observer 的橋接機制已下放到 ``backend.services.jobs``,本檔只負責 WS 端點
本身(連線、認證、串流、收尾),維持 ``api → services`` 的單向依賴。
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.auth.logto_jwt_verifier import _verifier as _jwt_verifier
from backend.services.jobs.job_manager import job_manager
from backend.services.jobs.progress_hub import progress_hub

# WebSocket 關閉碼:政策違反(認證失敗 / 非 job 擁有者)
_WS_CLOSE_POLICY_VIOLATION = 1008

router = APIRouter()


def _authorize(job_id: str, token: str) -> bool:
    """帶 token 時驗 JWT 並確認該 user 擁有此 job;驗不過或非擁有者回 False。"""
    try:
        user_id = _jwt_verifier.verify(token)
    except HTTPException:
        return False
    job = job_manager.get(job_id)
    # job 尚未建立(競態)時無從判斷擁有者:保守放行,capability 仍受 job_id 保護
    if job is None:
        return True
    return job.user_id == user_id


async def _consume_incoming(websocket: WebSocket) -> None:
    """持續吸收並丟棄客戶端入站訊息(本端點僅單向推播);客戶端關閉時拋 ``WebSocketDisconnect``。"""
    while True:
        await websocket.receive_text()


async def _stream_events(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """
    串流佇列事件直到哨兵或斷線。

    以一個常駐 receiver task 偵測斷線(空事件期也能即時察覺),與 ``queue.get()`` 競賽:
    收到哨兵 ``None`` 正常返回;receiver 先完成(斷線)則重拋 ``WebSocketDisconnect`` 給外層收尾。
    """
    receiver = asyncio.create_task(_consume_incoming(websocket))
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {getter, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            if receiver in done:
                getter.cancel()
                receiver.result()  # 斷線→重拋 WebSocketDisconnect;正常結束則無事
                return
            msg = getter.result()
            if msg is None:        # 哨兵:job 結束,正常收尾
                return
            await websocket.send_text(msg)
    finally:
        receiver.cancel()
        # CancelledError 於 Python 3.8+ 繼承 BaseException,不被 suppress(Exception) 攔下;
        # 須顯式納入,否則 job 正常結束(收到哨兵 return)後 cancel(receiver) 的 await 會把
        # CancelledError 拋進 ASGI,uvicorn 記為 "Exception in ASGI application"。
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await receiver


@router.websocket("/ws/progress/{job_id}")
async def progress_ws(websocket: WebSocket, job_id: str, token: Optional[str] = None) -> None:
    """
    訂閱某 job 的進度事件流。

    先送 replay(補播開頭事件)再串流即時事件;``?token=`` 有帶才驗 JWT + 比對 job 擁有者,
    不帶則以 job_id 當 capability 放行(符合無 token 的 wscat 驗收)。
    """
    await websocket.accept()
    if token is not None and not _authorize(job_id, token):
        await websocket.close(code=_WS_CLOSE_POLICY_VIOLATION)
        return

    replay, queue = progress_hub.attach(job_id)
    try:
        for msg in replay:
            await websocket.send_text(msg)
        await _stream_events(websocket, queue)
    except WebSocketDisconnect:
        # 客戶端斷線:正常情況,僅做清理
        pass
    finally:
        progress_hub.detach(job_id, queue)
