"""
Facade Pattern：專案管理 API 端點

封裝使用者專案資料夾的建立、列表、刪除操作，
以 JWT 驗證確保使用者只能存取自己的專案。
"""

import asyncio
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.auth.logto_jwt_verifier import verify_token
from backend.services.ingestion_provider import cloud_ingestion_service
from backend.services.project_meta_store import project_meta_store
from config.app_config import ASSETS_DIR
from ingestion_engine.models import (
    META_KEY_DRIVE_FOLDER_ID,
    META_KEY_LAST_SIGNATURE,
    META_KEY_LAST_SYNC_ERROR,
    META_KEY_LAST_SYNCED_AT,
    META_KEY_PHASE1_STATUS,
    META_KEY_PHASE1_UPDATED_AT,
    META_KEY_SOURCE,
    META_KEY_SOURCE_URL,
    META_KEY_SYNC_STATUS,
    PHASE1_STATUS_PENDING,
    SOURCE_GDRIVE,
    SYNC_STATUS_ACTIVE,
    SyncReport,
)

router = APIRouter()

# 背景首同步任務的強參照集合：避免 asyncio.create_task 的任務被 GC 提早回收
_background_tasks: set[asyncio.Task] = set()

_ASSETS_BASE_PATH = ASSETS_DIR

# --- 允許的媒體副檔名（用於計算素材數量）---
_MEDIA_EXTENSIONS = {'.mp4', '.mov', '.jpg', '.jpeg', '.png', '.heic', '.heif', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}


class CreateProjectRequest(BaseModel):
    """以顯示名稱建立空白本地專案的請求體。"""

    display_name: str


class CreateFromDriveRequest(BaseModel):
    """以 Drive 公開資料夾連結建立雲端來源專案的請求體。"""

    display_name: str
    # Google Drive 資料夾分享連結（需設為「知道連結的人可檢視」）；亦接受裸資料夾 ID
    source_url: str


class ProjectMeta(BaseModel):
    """專案中繼資料；雲端來源欄位僅雲端 project 有值，手動建立的本地 project 為 None。"""

    name: str
    display_name: str
    created_at: str
    last_modified: str
    asset_count: int
    has_blueprint: bool
    # 雲端來源同步觀測欄位（對應 project_meta.json 的雲端鍵）
    source: Optional[str] = None
    source_url: Optional[str] = None
    phase1_status: Optional[str] = None
    sync_status: Optional[str] = None
    last_synced_at: Optional[str] = None
    last_sync_error: Optional[str] = None


# --- 工具函式 ---

def _slugify(text: str) -> str:
    """將任意顯示名稱轉換為 URL 安全的資料夾名稱（僅保留 a-z0-9 與底線）。"""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug, flags=re.UNICODE)
    slug = re.sub(r'[\s\-]+', '_', slug)
    slug = re.sub(r'[^a-z0-9_]', '', slug)
    slug = slug.strip('_')
    return slug or "project"


def _user_dir(user_id: str) -> str:
    """取得使用者的根資料夾路徑，不存在時自動建立。"""
    path = os.path.join(_ASSETS_BASE_PATH, user_id)
    os.makedirs(path, exist_ok=True)
    return path


def _count_assets(project_dir: str) -> int:
    """計算專案資料夾內的媒體素材數量（排除 JSON 快取與 meta）。"""
    count = 0
    for fname in os.listdir(project_dir):
        ext = os.path.splitext(fname)[1].lower()
        if ext in _MEDIA_EXTENSIONS:
            count += 1
    return count


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allocate_unique_name(user_root: str, base_name: str) -> str:
    """在 user 根目錄下為 base_name 配置不衝突的資料夾名（重名時加時間戳與序號後綴）。"""
    name = base_name
    counter = 1
    while os.path.exists(os.path.join(user_root, name)):
        suffix = datetime.now().strftime("%m%d%H%M")
        name = f"{base_name}_{suffix}_{counter}"
        counter += 1
    return name


# --- API 端點 ---

@router.get("/projects", response_model=list[ProjectMeta])
async def list_projects(user_id: str = Depends(verify_token)):
    """列出目前登入使用者的所有專案；單一專案 meta 損毀不影響其餘專案的列出。"""
    user_root = _user_dir(user_id)
    projects = []
    for name in sorted(os.listdir(user_root)):
        project_dir = os.path.join(user_root, name)
        if not os.path.isdir(project_dir):
            continue
        try:
            # store.read 已容錯：缺檔 / 無法復原回 None，損毀但可復原則自動修復後回傳
            meta = project_meta_store.read(project_dir)
            if meta is None:
                # 沒有 meta（或損毀到無法復原）的資料夾：自動補建（相容舊資料 + 自我修復）
                meta = {
                    "name": name,
                    "display_name": name,
                    "created_at": _now_iso(),
                    "last_modified": _now_iso(),
                    "asset_count": _count_assets(project_dir),
                    "has_blueprint": os.path.exists(os.path.join(project_dir, "phase4_blueprint.json")),
                }
                project_meta_store.write(project_dir, meta)
            projects.append(meta)
        except Exception as exc:  # noqa: BLE001 - 單一專案的任何意外都不該讓整份列表 500
            print(f"[Projects Error] 略過無法讀取的專案 '{name}': {exc}")
            continue
    print(f"[Projects] 列出使用者 '{user_id[:8]}...' 的 {len(projects)} 個專案")
    return projects


@router.post("/projects", response_model=ProjectMeta, status_code=201)
async def create_project(req: CreateProjectRequest, user_id: str = Depends(verify_token)):
    """建立新專案資料夾，資料夾名稱由後端從 display_name slugify 產生。"""
    if not req.display_name.strip():
        raise HTTPException(status_code=400, detail="專案名稱不能為空")

    user_root = _user_dir(user_id)
    name = _allocate_unique_name(user_root, _slugify(req.display_name))

    project_dir = os.path.join(user_root, name)
    os.makedirs(project_dir, exist_ok=True)

    now = _now_iso()
    meta = {
        "name": name,
        "display_name": req.display_name.strip(),
        "created_at": now,
        "last_modified": now,
        "asset_count": 0,
        "has_blueprint": False,
    }
    project_meta_store.write(project_dir, meta)

    print(f"[Projects] 建立新專案: '{name}' (使用者 '{user_id[:8]}...')")
    return meta


@router.post("/projects/from-drive", response_model=ProjectMeta, status_code=201)
async def create_project_from_drive(req: CreateFromDriveRequest, user_id: str = Depends(verify_token)):
    """
    以 Drive 公開資料夾連結建立一個雲端來源專案，並立即在背景啟動首次同步。

    解析連結取得資料夾 ID → 建立 project 資料夾與含雲端來源欄位的 meta → 排程背景首同步
    （下載素材 + 觸發 Phase 1）；同步失敗會由背景 poller 下輪自動重試。
    """
    if not req.display_name.strip():
        raise HTTPException(status_code=400, detail="專案名稱不能為空")
    try:
        folder_id = cloud_ingestion_service.parse_source(req.source_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_root = _user_dir(user_id)
    name = _allocate_unique_name(user_root, _slugify(req.display_name))
    project_dir = os.path.join(user_root, name)
    os.makedirs(project_dir, exist_ok=True)

    now = _now_iso()
    meta = {
        "name": name,
        "display_name": req.display_name.strip(),
        "created_at": now,
        "last_modified": now,
        "asset_count": 0,
        "has_blueprint": False,
        # 雲端來源連結與同步狀態欄位（poller 以 source=gdrive 辨識需同步的 project）
        META_KEY_SOURCE: SOURCE_GDRIVE,
        META_KEY_DRIVE_FOLDER_ID: folder_id,
        META_KEY_SOURCE_URL: req.source_url.strip(),
        META_KEY_SYNC_STATUS: SYNC_STATUS_ACTIVE,
        META_KEY_PHASE1_STATUS: PHASE1_STATUS_PENDING,
        META_KEY_PHASE1_UPDATED_AT: None,
        META_KEY_LAST_SIGNATURE: "",
        META_KEY_LAST_SYNCED_AT: None,
        META_KEY_LAST_SYNC_ERROR: None,
    }
    project_meta_store.write(project_dir, meta)
    _schedule_first_sync(user_id, name)

    print(f"[Projects] 建立雲端來源專案: '{name}' (使用者 '{user_id[:8]}...')")
    return meta


@router.post("/projects/{project_name}/sync", response_model=SyncReport)
async def sync_project(project_name: str, user_id: str = Depends(verify_token)):
    """手動觸發一次雲端同步；阻塞的 Drive API／Phase 1 丟到 thread 執行，不卡 event loop。"""
    project_dir = os.path.join(_user_dir(user_id), project_name)
    if not os.path.isdir(project_dir):
        raise HTTPException(status_code=404, detail=f"找不到專案: {project_name}")
    try:
        return await asyncio.to_thread(cloud_ingestion_service.sync_project, user_id, project_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"找不到專案: {project_name}")


def _schedule_first_sync(user_id: str, project_name: str) -> None:
    """排程一次背景首同步（不阻塞請求）；任務參照存入集合避免被 GC 提早回收。"""
    task = asyncio.create_task(
        asyncio.to_thread(cloud_ingestion_service.sync_project, user_id, project_name)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.delete("/projects/{project_name}", status_code=204)
async def delete_project(project_name: str, user_id: str = Depends(verify_token)):
    """刪除使用者的指定專案（含資料夾內所有素材）。"""
    user_root = _user_dir(user_id)
    project_dir = os.path.join(user_root, project_name)

    if not os.path.isdir(project_dir):
        raise HTTPException(status_code=404, detail=f"找不到專案: {project_name}")

    shutil.rmtree(project_dir)
    print(f"[Projects] 已刪除專案: '{project_name}' (使用者 '{user_id[:8]}...')")
