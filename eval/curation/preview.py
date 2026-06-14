"""產生人工檢視用的 HTML contact sheet（可直接播放影片 / 看圖片）。

每件列出可播放的 `<video>`（影片）或 `<img>`（圖片）、cache_key、類型、時長、解析度、來源、作者、
授權與品質分。媒體以相對路徑連結本機檔，整個 work 目錄可離線開啟與播放。
"""
from __future__ import annotations

import html
import os
from pathlib import Path

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


class HtmlPreviewBuilder:
    """contact sheet 產生器。"""

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
        cards = "\n".join(self._render_card(c, output_path.parent) for c in candidates)
        video_count = sum(1 for c in candidates if not c.is_image)
        image_count = sum(1 for c in candidates if c.is_image)
        header = (
            f"<h1>{html.escape(group.group_id)} — {html.escape(group.theme)}"
            f"（scope={html.escape(group.scope or '-')}）</h1>"
            f"<div class='meta'>候選 {len(candidates)} 件（影片 {video_count}、圖片 {image_count}）；"
            f"秒數預算 {target_seconds:.0f}s</div>"
        )
        document = (
            "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<title>{html.escape(group.group_id)} preview</title><style>{_PAGE_CSS}</style></head>"
            f"<body>{header}<div class='grid'>{cards}</div></body></html>"
        )
        output_path.write_text(document, encoding="utf-8")
        logger.debug("已產生預覽頁：%s", output_path)

    def _render_card(self, candidate: ClipCandidate, base_dir: Path) -> str:
        """渲染單張卡片。"""
        media_html = self._render_media(candidate, base_dir)
        score = candidate.quality_score if candidate.quality_score is not None else 0.0
        badge_cls = "image" if candidate.is_image else "video"
        return (
            "<div class='card'>"
            f"{media_html}"
            f"<div class='key'>{html.escape(candidate.cache_key)}</div>"
            f"<div class='row'><span class='badge {badge_cls}'>{candidate.media_type.value}</span> "
            f"{candidate.duration_sec:.0f}s ・ {candidate.width}x{candidate.height}</div>"
            f"<div class='row'>{html.escape(candidate.source_platform.value)} ・ q={score:.2f}</div>"
            f"<div class='row'>作者：{html.escape(candidate.author_name)}</div>"
            f"<div class='row'>授權：{html.escape(candidate.license)}</div>"
            "</div>"
        )

    def _render_media(self, candidate: ClipCandidate, base_dir: Path) -> str:
        """影片渲染成可播放 `<video>`，圖片渲染成 `<img>`；缺檔則退回縮圖或佔位。"""
        if candidate.is_image:
            src = candidate.thumbnail_path or candidate.local_path
            return self._img_tag(src, base_dir, alt="image") or "<div class='media noimg'>（無圖）</div>"

        # 影片：本機檔在就內嵌可播放的 <video>，poster 用縮圖
        if candidate.local_path and Path(candidate.local_path).is_file():
            video_rel = os.path.relpath(candidate.local_path, start=base_dir)
            poster = ""
            if candidate.thumbnail_path and Path(candidate.thumbnail_path).is_file():
                poster_rel = os.path.relpath(candidate.thumbnail_path, start=base_dir)
                poster = f" poster='{html.escape(poster_rel)}'"
            return (
                f"<video class='media' controls preload='metadata'{poster}>"
                f"<source src='{html.escape(video_rel)}' type='video/mp4'></video>"
            )
        # 影片檔不在 → 退回縮圖
        return self._img_tag(candidate.thumbnail_path, base_dir, alt="thumb") or "<div class='media noimg'>（無預覽）</div>"

    @staticmethod
    def _img_tag(src_path: str | None, base_dir: Path, *, alt: str) -> str | None:
        """若本機檔存在則回 `<img>`，否則回 None。"""
        if src_path and Path(src_path).is_file():
            rel = os.path.relpath(src_path, start=base_dir)
            return f"<img class='media' src='{html.escape(rel)}' alt='{alt}'>"
        return None
