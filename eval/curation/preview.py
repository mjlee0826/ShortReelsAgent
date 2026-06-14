"""產生人工檢視用的 HTML contact sheet（縮圖牆）。

每段列出縮圖、cache_key、時長、解析度、來源、作者、授權與品質分，方便人工挑選。縮圖以相對路徑
連結，整個 work 目錄可離線開啟。
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
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }
.card { background: #fff; border: 1px solid #e2e2e2; border-radius: 8px; padding: 8px; }
.card img { width: 100%; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 4px; background: #eee; }
.card .key { font-weight: 600; margin-top: 6px; word-break: break-all; }
.card .row { color: #444; font-size: 13px; }
.noimg { display: flex; align-items: center; justify-content: center; aspect-ratio: 9 / 16;
         background: #eee; color: #999; border-radius: 4px; }
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
        """把候選清單渲染成 HTML 檔。

        參數
            group: 組規格（標題用）。
            candidates: 已評分並排序好的候選（依品質由高到低）。
            target_seconds: 該組秒數預算（標頭顯示）。
            output_path: 輸出 HTML 路徑。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cards = "\n".join(self._render_card(c, output_path.parent) for c in candidates)
        total_seconds = sum(c.duration_sec for c in candidates)
        header = (
            f"<h1>{html.escape(group.group_id)} — {html.escape(group.theme)}</h1>"
            f"<div class='meta'>候選 {len(candidates)} 段、總時長 {total_seconds:.0f}s；"
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
        if candidate.thumbnail_path and Path(candidate.thumbnail_path).is_file():
            rel = os.path.relpath(candidate.thumbnail_path, start=base_dir)
            img = f"<img src='{html.escape(rel)}' alt='thumb'>"
        else:
            img = "<div class='noimg'>（無縮圖）</div>"

        score = candidate.quality_score if candidate.quality_score is not None else 0.0
        return (
            "<div class='card'>"
            f"{img}"
            f"<div class='key'>{html.escape(candidate.cache_key)}</div>"
            f"<div class='row'>{candidate.duration_sec:.0f}s ・ {candidate.width}x{candidate.height}</div>"
            f"<div class='row'>{html.escape(candidate.source_platform.value)} ・ q={score:.2f}</div>"
            f"<div class='row'>作者：{html.escape(candidate.author_name)}</div>"
            f"<div class='row'>授權：{html.escape(candidate.license)}</div>"
            "</div>"
        )
