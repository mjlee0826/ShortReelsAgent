"""
導演 agentic loop「進行中對話狀態」儲存庫 (Repository Pattern)。

B2 suspend/resume：導演呼叫 ``ask_user`` 暫停時，把續跑所需狀態落地成每專案一份 ``agent_session.json``；
使用者答完由 ``/generate/resume`` 載回續跑，生成完成 / 失敗即清除（非長存）。沿用 ``snapshot_store`` 的
原子寫 + 容錯讀 + per-path 鎖慣例。
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from pydantic import BaseModel, Field

from backend.utils.atomic_json import atomic_write_json, read_json_tolerant
from config.project_artifacts import AGENT_SESSION_FILENAME


class AgentSession(BaseModel):
    """進行中導演對話的續跑狀態（值物件，可直接 JSON 落地 / 載回）。"""

    # loop 續跑狀態（system_prompt / messages / 待回 tool_results / ask 的 tool_use_id / viewed / corrections）
    resume_state: dict
    # 待回答的問題與選項（供前端顯示）
    question: str = ""
    options: list = Field(default_factory=list)
    # 後處理續跑所需的請求脈絡（resume 重建 final blueprint 用）
    prompt: str = ""
    is_refinement: bool = False
    subtitles: bool = True
    filters: bool = True
    regenerate_music: bool = True
    previous_bgm_track: Optional[dict] = None
    old_timeline: Optional[dict] = None
    folder_name: str = ""


class AgentSessionStore:
    """``agent_session.json`` 的原子寫 / 容錯讀 / 清除儲存庫（per-path 鎖序列化讀-改-寫）。"""

    def __init__(self) -> None:
        """初始化 per-path 鎖登錄表。"""
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def save(self, project_dir: str, session: AgentSession) -> None:
        """原子落地進行中的對話狀態（覆寫前一份）。"""
        path = self._path(project_dir)
        with self._lock_for(path):
            atomic_write_json(path, session.model_dump())

    def load(self, project_dir: str) -> Optional[AgentSession]:
        """容錯讀回進行中的對話狀態；缺檔 / 損毀 / 結構不符回 None。"""
        data = read_json_tolerant(self._path(project_dir), None)
        if not isinstance(data, dict):
            return None
        try:
            return AgentSession(**data)
        except Exception:  # noqa: BLE001 - 結構不符視同無有效 session
            return None

    def clear(self, project_dir: str) -> None:
        """清除進行中的對話狀態（完成 / 失敗後呼叫）；不存在則靜默忽略。"""
        path = self._path(project_dir)
        with self._lock_for(path):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    @staticmethod
    def _path(project_dir: str) -> str:
        """組出 session 檔的絕對路徑。"""
        return os.path.join(project_dir, AGENT_SESSION_FILENAME)

    def _lock_for(self, path: str) -> threading.Lock:
        """取得某 session 檔專屬的鎖（不存在則延遲建立）。"""
        with self._locks_guard:
            lock = self._locks.get(path)
            if lock is None:
                lock = threading.Lock()
                self._locks[path] = lock
            return lock


# 模組級單例（與其他 store 一致的使用慣例）
agent_session_store = AgentSessionStore()
