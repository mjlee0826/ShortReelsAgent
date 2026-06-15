"""
偏好資料集建置 (偏好資料飛輪 T1,離線批次)。

掃描 ``ASSETS_DIR`` 下所有專案,讀取 T0 捕捉的偏好產物(``phase4_blueprint_ai_original.json`` /
``preference_events.json`` / ``phase4_blueprint.json``),還原成兩類乾淨偏好配對,並逐對跑欄位級
diff(見 :mod:`blueprint_diff`):

- **refinement(指令↔修正)**:每筆微調事件的 ``before + prompt → after``。
- **manual_edit(AI 排 X→人改 Y)**:相鄰 AI 輸出與其後的人改版;最後一段為「最後一次 AI 版 →
  最終 phase4」(由離線比對補上)。

輸出(預設寫到 ``--out`` 目錄):
- ``preference_dataset.jsonl``:每行一筆配對(含 before / after / diff / prompt / 來源 / 類型)。
- ``preference_field_stats.json`` 與 ``preference_field_report.md``:各欄位被改次數排行
  ——即「導演哪裡最弱」的評測訊號(T2 評測報告)。

用法(自 repo 根目錄執行):
    python -m tools.preference_flywheel.build_dataset [--assets-dir DIR] [--out DIR]

註:本工具為離線一次性批次(非 server 併發路徑),輸出檔以一般 ``open('w')`` 寫入即可;
NFS 原子寫入規範僅約束 server runtime 的併發產物。
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Optional

from config.app_config import ASSETS_DIR
from config.project_artifacts import (
    PHASE4_BLUEPRINT_AI_ORIGINAL_FILENAME,
    PHASE4_BLUEPRINT_FILENAME,
    PREFERENCE_EVENTS_FILENAME,
)
from tools.preference_flywheel.blueprint_diff import BlueprintDiff, diff_blueprint, normalize_path

# 預設輸出目錄(相對 repo 根目錄;離線產物,與 server 產物分開存放)
_DEFAULT_OUT_DIR = "preference_dataset_out"

# stats 報告中列出的欄位排行上限(具名常數,禁 magic number)
_REPORT_TOP_N = 40


def _read_json(path: str) -> Optional[object]:
    """容錯讀 JSON;缺檔 / 損毀回 None(離線工具,壞檔略過即可)。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[build_dataset Warning] 讀取失敗,略過: {path} ({exc})")
        return None


def discover_project_dirs(assets_dir: str) -> list[str]:
    """掃出所有「含偏好捕捉產物」的專案目錄(以事件檔 / AI 原版檔為標記,深度不限)。"""
    found: list[str] = []
    for root, _dirs, files in os.walk(assets_dir):
        if PREFERENCE_EVENTS_FILENAME in files or PHASE4_BLUEPRINT_AI_ORIGINAL_FILENAME in files:
            found.append(root)
    return found


def _make_record(project: str, pair_type: str, prompt: str,
                 before: Optional[dict], after: Optional[dict], ts: Optional[str]) -> tuple[dict, BlueprintDiff]:
    """組一筆資料集記錄(含 diff),回傳(記錄 dict, diff 物件)供寫檔與統計共用。"""
    d = diff_blueprint(before, after)
    record = {
        "project": project,
        "pair_type": pair_type,
        "prompt": prompt,
        "ts": ts,
        "before": before,
        "after": after,
        "diff": d.to_dict(),
    }
    return record, d


def build_pairs(project: str, events: list[dict],
                ai_original: Optional[dict], final_phase4: Optional[dict]) -> list[tuple[dict, BlueprintDiff]]:
    """依事件鏈 + 最終 phase4 還原一個專案的所有偏好配對(尚未過濾空 diff)。"""
    pairs: list[tuple[dict, BlueprintDiff]] = []
    # 依時間排序(append 本即有序,排序僅為防呆)
    events = sorted(events, key=lambda e: e.get("ts") or "")

    prev_after: Optional[dict] = None  # 上一個 AI 輸出,供 manual_edit 當「AI 排 X」
    for ev in events:
        before = ev.get("before")
        after = ev.get("after")
        if ev.get("is_refinement"):
            # 指令↔修正:微調前(人改後)藍圖 + 指令 → AI 修正結果
            pairs.append(_make_record(project, "refinement", ev.get("prompt", "") or "",
                                      before, after, ev.get("ts")))
            # 手動編輯:上一個 AI 輸出 → 本次微調的 before(即上一段被人改後的版本)
            if prev_after is not None and before is not None:
                pairs.append(_make_record(project, "manual_edit", "", prev_after, before, ev.get("ts")))
        if after is not None:
            prev_after = after

    # 最後一段:最後一次 AI 輸出 → 最終 phase4(autosave 後的人改版)
    last_after = prev_after if prev_after is not None else ai_original
    if last_after is not None and final_phase4 is not None:
        pairs.append(_make_record(project, "manual_edit", "", last_after, final_phase4, None))

    return pairs


def _accumulate_stats(diff: BlueprintDiff, field_counter: Counter, pair_type: str, type_counter: Counter) -> None:
    """把一筆 diff 的變動累進統計:欄位被改次數 + 配對類型分佈。"""
    type_counter[pair_type] += 1
    for ch in diff.changes:
        field_counter[normalize_path(ch.path)] += 1
    # 結構級變動也計入(增 / 刪 / 重排亦是導演排版被推翻的訊號)
    for _ in diff.clips_added:
        field_counter["clip.added"] += 1
    for _ in diff.clips_removed:
        field_counter["clip.removed"] += 1
    if diff.clips_reordered:
        field_counter["clip.reordered"] += 1
    for _ in diff.text_added:
        field_counter["text_overlay.added"] += 1
    for _ in diff.text_removed:
        field_counter["text_overlay.removed"] += 1


def _write_report(out_dir: str, field_counter: Counter, type_counter: Counter, total_pairs: int) -> None:
    """輸出統計 JSON + Markdown 報告(導演弱點訊號)。"""
    ranked = field_counter.most_common()
    stats = {
        "total_pairs": total_pairs,
        "pair_type_distribution": dict(type_counter),
        "field_change_counts": dict(ranked),
    }
    with open(os.path.join(out_dir, "preference_field_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    lines = [
        "# 導演偏好弱點報告(偏好資料飛輪 T1 / T2 評測訊號)",
        "",
        f"- 偏好配對總數:**{total_pairs}**",
        f"- 配對類型分佈:{dict(type_counter)}",
        "",
        f"## 最常被使用者修改的欄位(前 {_REPORT_TOP_N})",
        "",
        "| 欄位 | 被改次數 |",
        "| --- | ---: |",
    ]
    for path, count in ranked[:_REPORT_TOP_N]:
        lines.append(f"| `{path}` | {count} |")
    lines.append("")
    with open(os.path.join(out_dir, "preference_field_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    """CLI 進入點:掃描、還原配對、過濾空 diff、寫資料集與統計報告。"""
    parser = argparse.ArgumentParser(description="偏好資料飛輪 T1:建置偏好資料集與導演弱點統計")
    parser.add_argument("--assets-dir", default=ASSETS_DIR, help=f"素材根目錄(預設 {ASSETS_DIR})")
    parser.add_argument("--out", default=_DEFAULT_OUT_DIR, help=f"輸出目錄(預設 {_DEFAULT_OUT_DIR})")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    project_dirs = discover_project_dirs(args.assets_dir)
    print(f"[build_dataset] 掃到 {len(project_dirs)} 個含偏好捕捉資料的專案")

    field_counter: Counter = Counter()
    type_counter: Counter = Counter()
    total_pairs = 0

    dataset_path = os.path.join(args.out, "preference_dataset.jsonl")
    with open(dataset_path, "w", encoding="utf-8") as out_f:
        for project_dir in project_dirs:
            # 以相對 assets_dir 的路徑當專案標籤(含 user_id/folder,便於回溯來源)
            project = os.path.relpath(project_dir, args.assets_dir)
            events = _read_json(os.path.join(project_dir, PREFERENCE_EVENTS_FILENAME)) or []
            ai_original = _read_json(os.path.join(project_dir, PHASE4_BLUEPRINT_AI_ORIGINAL_FILENAME))
            final_phase4 = _read_json(os.path.join(project_dir, PHASE4_BLUEPRINT_FILENAME))
            if not isinstance(events, list):
                events = []

            for record, diff in build_pairs(project, events, ai_original, final_phase4):
                # 過濾「人沒改任何東西」的雜訊配對:無 diff 即無偏好訊號
                if diff.is_empty():
                    continue
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                _accumulate_stats(diff, field_counter, record["pair_type"], type_counter)
                total_pairs += 1

    _write_report(args.out, field_counter, type_counter, total_pairs)
    print(f"[build_dataset] 完成:{total_pairs} 筆偏好配對 → {dataset_path}")
    print(f"[build_dataset] 統計報告 → {os.path.join(args.out, 'preference_field_report.md')}")


if __name__ == "__main__":
    main()
