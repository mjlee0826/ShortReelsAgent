#!/usr/bin/env bash
#
# MIGRATE.sh — 既有資料一次性遷移（B 方案：素材身分檔名 → relpath + raw/standardized 分層）
# ===========================================================================================
#
# 用途：把「舊結構」的既有專案就地遷移成「新結構」，讓 B 方案上線後既有專案仍可用。
#   舊結構：{ASSETS_DIR}/{user}/{project}/ 下原始檔與 _std 衍生檔全擠在 project 根目錄，
#           且 status / metadata / project_meta / blueprint 的 key 皆為 basename（檔名）。
#   新結構：原始檔搬進 raw/、_std 衍生檔搬進 standardized/；上述 JSON 的 key 改寫為 relpath
#           （raw/xxx 或 standardized/xxx_std.yyy）。所有 JSON 仍留在 project 根目錄。
#
# 對應 REFACTOR_TASK.md 第 6 章「選項一：一次性 migration script」。
#
# 重要：
#   * 本腳本會「動到使用者資料」。請務必在 Leibniz（實際資料所在機）執行，且建議：
#       1) 先停掉後端（避免遷移與服務同時讀寫同一專案產生競態）。
#       2) 先用 --dry-run 看清楚會搬哪些檔、改哪些 JSON，確認無誤再正式跑。
#   * 遷移為 idempotent（可重複執行）：已搬移 / 已改寫者會自動略過。
#   * JSON 一律以「唯一 temp + os.replace」原子寫回（遵守本專案 NFS 上禁直寫的慣例）。
#
# 用法：
#   ./MIGRATE.sh [--dry-run] [--assets-dir=/path/to/assets]
#   ASSETS_DIR=/path/to/assets ./MIGRATE.sh --dry-run
#
# 參數：
#   --dry-run            只印出將進行的搬移 / 改寫，不實際更動任何檔案。
#   --assets-dir=PATH    指定素材根目錄（預設沿用環境變數 ASSETS_DIR，再退回 app_config 預設值）。
#   -h, --help           顯示說明。
#
set -euo pipefail

# 與 config/app_config.py 的 ASSETS_DIR 預設值一致（可由環境變數或 --assets-dir 覆寫）
ASSETS_DIR="${ASSETS_DIR:-/data1/cache/mjlee/assets}"
DRY_RUN=0

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
}

# --- 參數解析 ---
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --assets-dir=*) ASSETS_DIR="${1#*=}" ;;
    --assets-dir) shift; ASSETS_DIR="${1:-}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知參數: $1（用 --help 看說明）" >&2; exit 1 ;;
  esac
  shift
done

# --- 前置檢查 ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "找不到 python3，無法執行遷移（JSON 改寫需要 Python）。" >&2
  exit 1
fi
if [ ! -d "$ASSETS_DIR" ]; then
  echo "找不到素材根目錄 ASSETS_DIR: $ASSETS_DIR" >&2
  exit 1
fi

echo "========================================================================"
echo " B 方案資料遷移：raw/standardized 分層 + JSON key 路徑化"
echo " 素材根目錄 : $ASSETS_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  echo " 模式       : DRY-RUN（僅預覽，不更動檔案）"
else
  echo " 模式       : 正式執行（會搬移檔案並改寫 JSON）"
fi
echo "========================================================================"

# 實際遷移邏輯交給內嵌的 Python（檔案搬移 + JSON 原子改寫，邏輯與後端 asset_discovery 一致）
ASSETS_DIR="$ASSETS_DIR" DRY_RUN="$DRY_RUN" python3 - <<'PY'
import json
import os
import sys
import tempfile

ASSETS_DIR = os.environ["ASSETS_DIR"]
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# --- 與後端一致的分層常數（config/app_config.py / media_standardizer 同源，避免漂移）---
RAW_SUBDIR = "raw"
STANDARDIZED_SUBDIR = "standardized"
STD_MARKER = "_std."  # 標準化輸出檔名標記（與 media_standardizer._STD_MARKER 一致）

# 需搬進 raw/ 的原始素材副檔名（圖片 / 影片 / 音訊；_std 衍生另以 STD_MARKER 判定進 standardized/）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
MOVABLE_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS

# 留在 project 根目錄、且需把 basename key 改寫為 relpath 的 JSON 檔
STATUS_FILE = "phase1_asset_status.json"        # dict：{basename: {asset_id, status, ...}}
METADATA_FILE = "phase1_assets_metadata.json"   # list：[{file, metadata, ...}]
META_FILE = "project_meta.json"                 # dict：asset_strategies / analyzed_strategies / dirty_assets
BLUEPRINT_FILE = "phase4_blueprint.json"        # 巢狀：timeline clips 與 pip_video 的 clip_id


def to_relpath(name):
    """
    basename → relpath 身分：含 _std. 者進 standardized/，其餘進 raw/。

    先 basename 去除任何既有目錄（相容舊的絕對路徑 file，亦讓重複執行 idempotent）。
    此規則與新版 collect_asset_files 的回傳身分完全一致。
    """
    base = os.path.basename(name)
    sub = STANDARDIZED_SUBDIR if STD_MARKER in base else RAW_SUBDIR
    return f"{sub}/{base}"


def subdir_for(filename):
    """決定某 root 檔案該搬到哪個子目錄；非素材 / 音訊（如 .json）回 None 表示不動。"""
    if STD_MARKER in filename:
        return STANDARDIZED_SUBDIR
    if os.path.splitext(filename)[1].lower() in MOVABLE_EXTS:
        return RAW_SUBDIR
    return None


def atomic_write_json(path, data):
    """以唯一 temp + os.replace 原子寫回 JSON（NFS 上禁直寫 open('w')，避免併發 / 半寫損毀）。"""
    if DRY_RUN:
        return
    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        # 寫入失敗清掉殘留 temp，再把原例外拋回
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_json(path):
    """讀取 JSON；交給呼叫端在 try 內處理 JSONDecodeError。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def migrate_files(project_dir):
    """把 project 根目錄的原始檔搬進 raw/、_std 衍生檔搬進 standardized/；回傳搬移檔數。"""
    moved = 0
    for name in sorted(os.listdir(project_dir)):
        src = os.path.join(project_dir, name)
        if not os.path.isfile(src):
            continue  # 略過 raw/ standardized/ 子目錄本身
        sub = subdir_for(name)
        if sub is None:
            continue  # JSON / 未知檔留在根目錄
        dst = os.path.join(project_dir, sub, name)
        if os.path.exists(dst):
            # 目標已存在（前次中斷 / 重複執行）：不覆蓋，僅提示
            print(f"      ! 跳過搬移（目標已存在）：{name} → {sub}/")
            continue
        print(f"      → 搬移 {name} → {sub}/")
        if not DRY_RUN:
            os.makedirs(os.path.join(project_dir, sub), exist_ok=True)
            os.rename(src, dst)  # 同檔系 rename 為原子操作
        moved += 1
    return moved


def rewrite_status(project_dir):
    """改寫 phase1_asset_status.json：dict 的 basename key（與內層 asset_id）→ relpath。"""
    path = os.path.join(project_dir, STATUS_FILE)
    if not os.path.exists(path):
        return 0
    data = load_json(path)
    if not isinstance(data, dict):
        return 0
    new = {}
    for key, entry in data.items():
        rel = to_relpath(key)
        # 狀態條目內亦帶 asset_id（_build_status_entry 寫入），一併同步為 relpath
        if isinstance(entry, dict) and "asset_id" in entry:
            entry["asset_id"] = rel
        new[rel] = entry
    if new == data:
        return 0
    print(f"      ✎ 改寫 {STATUS_FILE}（{len(new)} 筆 key → relpath）")
    atomic_write_json(path, new)
    return 1


def rewrite_metadata(project_dir):
    """改寫 phase1_assets_metadata.json：每筆 file（basename / 舊絕對路徑）→ relpath。"""
    path = os.path.join(project_dir, METADATA_FILE)
    if not os.path.exists(path):
        return 0
    data = load_json(path)
    if not isinstance(data, list):
        return 0
    changed = False
    for rec in data:
        if isinstance(rec, dict) and rec.get("file"):
            rel = to_relpath(rec["file"])
            if rel != rec["file"]:
                rec["file"] = rel
                changed = True
    if not changed:
        return 0
    print(f"      ✎ 改寫 {METADATA_FILE}（{len(data)} 筆 file → relpath）")
    atomic_write_json(path, data)
    return 1


def rewrite_meta(project_dir):
    """改寫 project_meta.json：asset_strategies / analyzed_strategies 的 key 與 dirty_assets 值 → relpath。"""
    path = os.path.join(project_dir, META_FILE)
    if not os.path.exists(path):
        return 0
    data = load_json(path)
    if not isinstance(data, dict):
        return 0
    changed = False
    for field in ("asset_strategies", "analyzed_strategies"):
        mapping = data.get(field)
        if isinstance(mapping, dict):
            remapped = {to_relpath(k): v for k, v in mapping.items()}
            if remapped != mapping:
                data[field] = remapped
                changed = True
    dirty = data.get("dirty_assets")
    if isinstance(dirty, list):
        remapped = sorted({to_relpath(x) for x in dirty})
        if remapped != dirty:
            data["dirty_assets"] = remapped
            changed = True
    if not changed:
        return 0
    print(f"      ✎ 改寫 {META_FILE}（策略 / dirty key → relpath）")
    atomic_write_json(path, data)
    return 1


def rewrite_clip_ids(obj):
    """遞迴改寫任意巢狀結構內 key 為 clip_id 的字串值 → relpath；回傳是否有變更。"""
    changed = False
    if isinstance(obj, dict):
        for key, value in obj.items():
            # clip_id 為素材身分（timeline clips 與 pip_video 皆有）；bgm 的 track_id 是 /cache URL，不動
            if key == "clip_id" and isinstance(value, str) and value:
                rel = to_relpath(value)
                if rel != value:
                    obj[key] = rel
                    changed = True
            elif rewrite_clip_ids(value):
                changed = True
    elif isinstance(obj, list):
        for item in obj:
            if rewrite_clip_ids(item):
                changed = True
    return changed


def rewrite_blueprint(project_dir):
    """改寫 phase4_blueprint.json：所有 clip_id（含 pip_video）→ relpath。"""
    path = os.path.join(project_dir, BLUEPRINT_FILE)
    if not os.path.exists(path):
        return 0
    data = load_json(path)
    if not rewrite_clip_ids(data):
        return 0
    print(f"      ✎ 改寫 {BLUEPRINT_FILE}（clip_id → relpath）")
    atomic_write_json(path, data)
    return 1


def migrate_project(project_dir):
    """遷移單一專案：先搬檔，再改寫四類 JSON 的 key；回傳 (搬移檔數, 改寫 JSON 數)。"""
    moved = migrate_files(project_dir)
    rewritten = 0
    for rewriter in (rewrite_status, rewrite_metadata, rewrite_meta, rewrite_blueprint):
        try:
            rewritten += rewriter(project_dir)
        except (json.JSONDecodeError, OSError) as exc:
            # 單一 JSON 壞檔不應中斷整體遷移；印出後續續跑（其餘專案與檔案不受影響）
            print(f"      ⚠ 略過無法處理的 JSON（{rewriter.__name__}）：{exc}")
    return moved, rewritten


def main():
    total_projects = total_moved = total_rewritten = 0
    for user in sorted(os.listdir(ASSETS_DIR)):
        user_dir = os.path.join(ASSETS_DIR, user)
        if not os.path.isdir(user_dir):
            continue
        for project in sorted(os.listdir(user_dir)):
            project_dir = os.path.join(user_dir, project)
            if not os.path.isdir(project_dir):
                continue
            print(f"  • {user}/{project}")
            moved, rewritten = migrate_project(project_dir)
            total_projects += 1
            total_moved += moved
            total_rewritten += rewritten

    print("------------------------------------------------------------------------")
    verb = "預計" if DRY_RUN else "已"
    print(f" 完成：掃描 {total_projects} 個專案，{verb}搬移 {total_moved} 個檔案、"
          f"{verb}改寫 {total_rewritten} 個 JSON。")
    if DRY_RUN:
        print(" （DRY-RUN：未實際更動任何檔案；確認無誤後拿掉 --dry-run 再正式執行。）")


main()
sys.exit(0)
PY

echo "========================================================================"
if [ "$DRY_RUN" -eq 1 ]; then
  echo " DRY-RUN 結束。確認上方搬移 / 改寫無誤後，拿掉 --dry-run 正式執行。"
else
  echo " 遷移完成。建議重啟後端，並依 REFACTOR_TASK.md 第 7 章做端到端驗證。"
fi
echo "========================================================================"
