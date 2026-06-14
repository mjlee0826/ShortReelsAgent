"""產生人工檢視用的 HTML contact sheet（可直接播放影片 / 看圖片）。

提供兩種輸出，共用同一套卡片／媒體渲染：
- ``HtmlPreviewBuilder``：寫出**唯讀**靜態 ``preview.html``（媒體以相對路徑連結，整個 work 目錄可離線開啟）。
- ``InteractivePreviewRenderer``：回傳**互動勾選頁** HTML 字串（給 serve 子指令的 server），每張卡片帶
  checkbox、頂部 sticky 工具列顯示已選秒數，勾選變動即自動 POST 寫回選取檔。媒體改用 ``/work`` 絕對路由。

媒體 URL 的差異由 ``MediaUrlResolver``（Strategy）封裝，渲染邏輯本身不感知是靜態或 server。
"""
from __future__ import annotations

import html
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import quote

from ..constants import (
    SELECTION_AUTOSAVE_DEBOUNCE_MS,
    SERVER_SAVE_ROUTE,
    SERVER_WORK_ROUTE,
)
from ..logging_setup import get_logger
from ..models import ClipCandidate, GroupSpec

logger = get_logger(__name__)

# 版面：CSS 用純字串（避免 f-string 大括號轉義困擾）
_PAGE_CSS: str = """
body { font-family: system-ui, "Noto Sans CJK TC", sans-serif; margin: 24px; background: #fafafa; }
h1 { font-size: 20px; } .meta { color: #555; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
.card { background: #fff; border: 1px solid #e2e2e2; border-radius: 8px; padding: 8px; }
.media { width: 100%; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 4px; background: #eee; display: block; }
.noimg { display: flex; align-items: center; justify-content: center; aspect-ratio: 9 / 16;
         background: #eee; color: #999; border-radius: 4px; }
.badge { display: inline-block; font-size: 12px; padding: 1px 6px; border-radius: 4px; color: #fff; }
.badge.video { background: #2563eb; } .badge.image { background: #16a34a; }
.card .key { font-weight: 600; margin-top: 6px; word-break: break-all; }
.card .row { color: #444; font-size: 13px; }
"""

# 互動頁專屬樣式：sticky 工具列、可選卡片、勾選提示
_INTERACTIVE_CSS: str = """
.toolbar { position: sticky; top: 0; z-index: 10; background: #1f2937; color: #fff;
           padding: 10px 14px; border-radius: 8px; margin-bottom: 16px; display: flex;
           align-items: center; gap: 12px; flex-wrap: wrap; }
.toolbar .count { font-weight: 600; }
.toolbar .over { color: #fca5a5; }
.toolbar button { background: #374151; color: #fff; border: 1px solid #4b5563;
                  border-radius: 6px; padding: 5px 10px; cursor: pointer; }
.toolbar button:hover { background: #4b5563; }
.toolbar .status { margin-left: auto; color: #9ca3af; font-size: 13px; }
.toolbar a { color: #93c5fd; text-decoration: none; }
.card.selectable.checked { outline: 2px solid #2563eb; }
.card .pick { display: flex; align-items: center; gap: 6px; font-size: 13px;
              margin-bottom: 6px; cursor: pointer; user-select: none; }
.card .pick input { width: 16px; height: 16px; }
"""


class MediaUrlResolver(ABC):
    """把候選的本機檔路徑轉成可在 HTML 中連結的 URL（Strategy）。"""

    @abstractmethod
    def url(self, local_path: str | None) -> str | None:
        """檔案存在且可連結時回傳 URL，否則回 None。"""
        raise NotImplementedError


class RelativeMediaUrl(MediaUrlResolver):
    """以相對路徑連結（給離線可開啟的靜態 preview.html 用）。"""

    def __init__(self, base_dir: Path) -> None:
        """base_dir 為 HTML 檔所在目錄，連結相對於它。"""
        self._base_dir = base_dir

    def url(self, local_path: str | None) -> str | None:
        """檔案存在則回相對於 base_dir 的路徑。"""
        if local_path and Path(local_path).is_file():
            return os.path.relpath(local_path, start=self._base_dir)
        return None


class WorkRootMediaUrl(MediaUrlResolver):
    """以 ``/work`` 絕對路由連結（給 server 串流；含 work_dir 內含防護）。"""

    def __init__(self, work_dir: Path) -> None:
        """work_dir 為媒體根目錄；只連結位於其下的檔案。"""
        self._work_dir = work_dir.resolve()

    def url(self, local_path: str | None) -> str | None:
        """檔案存在且位於 work_dir 內則回 ``/work/<相對路徑>``（URL 安全）。"""
        if not local_path:
            return None
        resolved = Path(local_path).resolve()
        if not resolved.is_file():
            return None
        try:
            rel = resolved.relative_to(self._work_dir)
        except ValueError:
            return None  # 不在 work_dir 底下：拒絕連結
        return f"{SERVER_WORK_ROUTE}/{quote(rel.as_posix())}"


class _CardRenderer:
    """單張卡片的媒體與 metadata 渲染（靜態與互動頁共用）。"""

    def media_html(self, candidate: ClipCandidate, resolver: MediaUrlResolver) -> str:
        """影片渲染成可播放 `<video>`，圖片渲染成 `<img>`；缺檔則退回縮圖或佔位。"""
        if candidate.is_image:
            src = candidate.thumbnail_path or candidate.local_path
            return self._img_tag(src, resolver, alt="image") or "<div class='media noimg'>（無圖）</div>"

        # 影片：本機檔在就內嵌可播放的 <video>，poster 用縮圖
        video_src = resolver.url(candidate.local_path)
        if video_src:
            poster = ""
            poster_src = resolver.url(candidate.thumbnail_path)
            if poster_src:
                poster = f" poster='{html.escape(poster_src)}'"
            return (
                f"<video class='media' controls preload='metadata'{poster}>"
                f"<source src='{html.escape(video_src)}' type='video/mp4'></video>"
            )
        # 影片檔不在 → 退回縮圖
        return self._img_tag(candidate.thumbnail_path, resolver, alt="thumb") or "<div class='media noimg'>（無預覽）</div>"

    def meta_html(self, candidate: ClipCandidate) -> str:
        """cache_key 與各項 metadata 列。"""
        score = candidate.quality_score if candidate.quality_score is not None else 0.0
        badge_cls = "image" if candidate.is_image else "video"
        return (
            f"<div class='key'>{html.escape(candidate.cache_key)}</div>"
            f"<div class='row'><span class='badge {badge_cls}'>{candidate.media_type.value}</span> "
            f"{candidate.duration_sec:.0f}s ・ {candidate.width}x{candidate.height}</div>"
            f"<div class='row'>{html.escape(candidate.source_platform.value)} ・ q={score:.2f}</div>"
            f"<div class='row'>作者：{html.escape(candidate.author_name)}</div>"
            f"<div class='row'>授權：{html.escape(candidate.license)}</div>"
        )

    @staticmethod
    def _img_tag(src_path: str | None, resolver: MediaUrlResolver, *, alt: str) -> str | None:
        """若可連結則回 `<img>`，否則回 None。"""
        src = resolver.url(src_path)
        if src:
            return f"<img class='media' src='{html.escape(src)}' alt='{alt}'>"
        return None


def _header_html(group: GroupSpec, candidates: list[ClipCandidate], target_seconds: float) -> str:
    """組標題與候選統計（靜態與互動頁共用）。"""
    video_count = sum(1 for c in candidates if not c.is_image)
    image_count = sum(1 for c in candidates if c.is_image)
    return (
        f"<h1>{html.escape(group.group_id)} — {html.escape(group.theme)}"
        f"（scope={html.escape(group.scope or '-')}）</h1>"
        f"<div class='meta'>候選 {len(candidates)} 件（影片 {video_count}、圖片 {image_count}）；"
        f"秒數預算 {target_seconds:.0f}s</div>"
    )


class HtmlPreviewBuilder:
    """唯讀靜態 contact sheet 產生器。"""

    def __init__(self) -> None:
        """建立卡片渲染器。"""
        self._cards = _CardRenderer()

    def build(
        self,
        group: GroupSpec,
        candidates: list[ClipCandidate],
        target_seconds: float,
        output_path: Path,
    ) -> None:
        """把候選清單渲染成 HTML 檔（影片可直接播放）。

        參數
            group: 組規格（標題用）。
            candidates: 已評分並依品質排序的候選。
            target_seconds: 該組秒數預算（標頭顯示）。
            output_path: 輸出 HTML 路徑。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        resolver = RelativeMediaUrl(output_path.parent)  # 靜態頁：相對於 HTML 所在目錄
        cards = "\n".join(self._render_card(c, resolver) for c in candidates)
        header = _header_html(group, candidates, target_seconds)
        document = (
            "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<title>{html.escape(group.group_id)} preview</title><style>{_PAGE_CSS}</style></head>"
            f"<body>{header}<div class='grid'>{cards}</div></body></html>"
        )
        output_path.write_text(document, encoding="utf-8")
        logger.debug("已產生預覽頁：%s", output_path)

    def _render_card(self, candidate: ClipCandidate, resolver: MediaUrlResolver) -> str:
        """渲染單張（唯讀）卡片。"""
        return (
            "<div class='card'>"
            f"{self._cards.media_html(candidate, resolver)}"
            f"{self._cards.meta_html(candidate)}"
            "</div>"
        )


# 互動頁前端 JS 範本：用 .replace 注入參數，避免 f-string 與 JS 大括號互相轉義
_INTERACTIVE_JS: str = """
const GROUP_ID = "__GROUP_ID__";
const TARGET_SECONDS = __TARGET_SECONDS__;
const SAVE_URL = "__SAVE_URL__";
const DEBOUNCE_MS = __DEBOUNCE_MS__;

const boxes = Array.from(document.querySelectorAll("input.sel"));
const countEl = document.getElementById("count");
const statusEl = document.getElementById("status");
let timer = null;

function checkedCards() {
  // 回傳已勾選的卡片清單（含 data-key / data-dur）
  return boxes.filter(b => b.checked).map(b => b.closest(".card"));
}

function updateToolbar() {
  const cards = checkedCards();
  let total = 0;
  cards.forEach(c => { total += parseFloat(c.dataset.dur || "0"); });
  boxes.forEach(b => b.closest(".card").classList.toggle("checked", b.checked));
  const over = total > TARGET_SECONDS ? " over" : "";
  countEl.className = "count" + over;
  countEl.textContent = "已選 " + cards.length + " 件 / " + total.toFixed(0)
    + "s（預算 " + TARGET_SECONDS.toFixed(0) + "s）";
}

async function save() {
  // 收集已勾選的 cache_key 並 POST 寫回選取檔
  const selected = checkedCards().map(c => c.dataset.key);
  statusEl.textContent = "儲存中…";
  try {
    const resp = await fetch(SAVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    statusEl.textContent = "已寫入 selections/" + GROUP_ID + ".txt（" + data.count + " 件）";
  } catch (err) {
    statusEl.textContent = "儲存失敗：" + err.message;
  }
}

function scheduleSave() {
  // debounce：最後一次變動後才存，避免連續勾選打太多 POST
  if (timer) clearTimeout(timer);
  timer = setTimeout(save, DEBOUNCE_MS);
}

boxes.forEach(b => b.addEventListener("change", () => { updateToolbar(); scheduleSave(); }));
document.getElementById("selectAll").addEventListener("click", () => {
  boxes.forEach(b => { b.checked = true; }); updateToolbar(); scheduleSave();
});
document.getElementById("clearAll").addEventListener("click", () => {
  boxes.forEach(b => { b.checked = false; }); updateToolbar(); scheduleSave();
});
updateToolbar();
"""


class InteractivePreviewRenderer:
    """互動勾選頁渲染器（回傳 HTML 字串，不寫檔；給 serve server 用）。"""

    def __init__(self) -> None:
        """建立卡片渲染器。"""
        self._cards = _CardRenderer()

    def render(
        self,
        group: GroupSpec,
        candidates: list[ClipCandidate],
        target_seconds: float,
        selected_keys: set[str],
        work_dir: Path,
    ) -> str:
        """渲染單組互動頁。

        參數
            group: 組規格。
            candidates: 已評分並依品質排序的候選。
            target_seconds: 該組秒數預算。
            selected_keys: 預先勾起的 cache_key 集合（依現有選取檔）。
            work_dir: 媒體根目錄（媒體連結走 /work 路由）。
        """
        resolver = WorkRootMediaUrl(work_dir)
        cards = "\n".join(
            self._render_card(c, resolver, c.cache_key in selected_keys) for c in candidates
        )
        header = _header_html(group, candidates, target_seconds)
        toolbar = (
            "<div class='toolbar'>"
            "<a href='/'>← 索引</a>"
            "<span id='count' class='count'></span>"
            "<button id='selectAll'>全選</button>"
            "<button id='clearAll'>清空</button>"
            "<span id='status' class='status'></span>"
            "</div>"
        )
        script = (
            _INTERACTIVE_JS
            .replace("__GROUP_ID__", group.group_id)
            .replace("__TARGET_SECONDS__", f"{target_seconds:.1f}")
            .replace("__SAVE_URL__", f"{SERVER_SAVE_ROUTE}/{quote(group.group_id)}")
            .replace("__DEBOUNCE_MS__", str(SELECTION_AUTOSAVE_DEBOUNCE_MS))
        )
        return (
            "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(group.group_id)} 勾選</title>"
            f"<style>{_PAGE_CSS}{_INTERACTIVE_CSS}</style></head>"
            f"<body>{header}{toolbar}<div class='grid'>{cards}</div>"
            f"<script>{script}</script></body></html>"
        )

    def _render_card(
        self, candidate: ClipCandidate, resolver: MediaUrlResolver, checked: bool
    ) -> str:
        """渲染單張可勾選卡片（data-key / data-dur 供前端計算）。"""
        checked_attr = " checked" if checked else ""
        return (
            f"<div class='card selectable' data-key='{html.escape(candidate.cache_key)}' "
            f"data-dur='{candidate.duration_sec:.1f}'>"
            f"<label class='pick'><input type='checkbox' class='sel'{checked_attr}> 選取</label>"
            f"{self._cards.media_html(candidate, resolver)}"
            f"{self._cards.meta_html(candidate)}"
            "</div>"
        )
