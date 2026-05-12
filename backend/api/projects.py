"""
Facade Pattern：專案管理 API 端點

封裝使用者專案資料夾的建立、列表、刪除操作，
以 JWT 驗證確保使用者只能存取自己的專案。
"""

import os
import re
import json
import shutil
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.auth.logto_jwt_verifier import verify_token

router = APIRouter()

_ASSETS_BASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

# --- 允許的媒體副檔名（用於計算素材數量）---
_MEDIA_EXTENSIONS = {'.mp4', '.mov', '.jpg', '.jpeg', '.png', '.heic', '.heif', '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}
_META_FILENAME = "project_meta.json"


class CreateProjectRequest(BaseModel):
    display_name: str


class ProjectMeta(BaseModel):
    name: str
    display_name: str
    created_at: str
    last_modified: str
    asset_count: int
    has_blueprint: bool


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


def _read_meta(project_dir: str) -> dict | None:
    """讀取專案的 project_meta.json；不存在時回傳 None。"""
    meta_path = os.path.join(project_dir, _META_FILENAME)
    if not os.path.exists(meta_path):
        return None
    with open(meta_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_meta(project_dir: str, meta: dict):
    """將 project_meta.json 寫入專案資料夾。"""
    meta_path = os.path.join(project_dir, _META_FILENAME)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


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


# --- API 端點 ---

@router.get("/projects", response_model=list[ProjectMeta])
async def list_projects(user_id: str = Depends(verify_token)):
    """列出目前登入使用者的所有專案。"""
    user_root = _user_dir(user_id)
    projects = []
    for name in sorted(os.listdir(user_root)):
        project_dir = os.path.join(user_root, name)
        if not os.path.isdir(project_dir):
            continue
        meta = _read_meta(project_dir)
        if meta is None:
            # 沒有 meta 檔案的資料夾：自動補建（相容舊資料）
            meta = {
                "name": name,
                "display_name": name,
                "created_at": _now_iso(),
                "last_modified": _now_iso(),
                "asset_count": _count_assets(project_dir),
                "has_blueprint": os.path.exists(os.path.join(project_dir, "phase4_blueprint.json")),
            }
            _write_meta(project_dir, meta)
        projects.append(meta)
    print(f"[Projects] 列出使用者 '{user_id[:8]}...' 的 {len(projects)} 個專案")
    return projects


@router.post("/projects", response_model=ProjectMeta, status_code=201)
async def create_project(req: CreateProjectRequest, user_id: str = Depends(verify_token)):
    """建立新專案資料夾，資料夾名稱由後端從 display_name slugify 產生。"""
    if not req.display_name.strip():
        raise HTTPException(status_code=400, detail="專案名稱不能為空")

    user_root = _user_dir(user_id)
    base_name = _slugify(req.display_name)

    # 處理重名：加時間戳後綴
    name = base_name
    counter = 1
    while os.path.exists(os.path.join(user_root, name)):
        suffix = datetime.now().strftime("%m%d%H%M")
        name = f"{base_name}_{suffix}_{counter}"
        counter += 1

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
    _write_meta(project_dir, meta)

    print(f"[Projects] 建立新專案: '{name}' (使用者 '{user_id[:8]}...')")
    return meta


@router.delete("/projects/{project_name}", status_code=204)
async def delete_project(project_name: str, user_id: str = Depends(verify_token)):
    """刪除使用者的指定專案（含資料夾內所有素材）。"""
    user_root = _user_dir(user_id)
    project_dir = os.path.join(user_root, project_name)

    if not os.path.isdir(project_dir):
        raise HTTPException(status_code=404, detail=f"找不到專案: {project_name}")

    shutil.rmtree(project_dir)
    print(f"[Projects] 已刪除專案: '{project_name}' (使用者 '{user_id[:8]}...')")
