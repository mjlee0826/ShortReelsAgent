"""serve 子指令：互動策展 server（本機、純 stdlib）。

提供帶 checkbox 的單組互動頁；勾選變動由前端 POST ``/save/<group_id>``，後端依選取覆寫
``selections/<group_id>.txt``（格式與手動範本相同，兩種方式可互換）。媒體檔由 ``/work`` 路由串流。

只綁 localhost、不對外開放；職責僅限「寫選取檔」——curate 的套用（複製到 curated、亂序命名、寫
summary）仍由 ``CurateStage`` 負責。

路由：
    GET  /                      → 各組索引頁
    GET  /group/<group_id>      → 單組互動勾選頁
    GET  /work/<path>           → 串流 work_dir 底下的媒體檔（含內含防護）
    POST /save/<group_id>       → 依 JSON {"selected":[cache_key,...]} 覆寫選取檔
"""
from __future__ import annotations

import html
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from ..constants import (
    DOWNLOAD_CHUNK_SIZE,
    SERVER_GROUP_ROUTE,
    SERVER_SAVE_ROUTE,
    SERVER_WORK_ROUTE,
)
from ..jsonio import read_models
from ..logging_setup import get_logger
from ..models import ClipCandidate, GroupSpec
from ..pipeline import BuildContext
from .preview import InteractivePreviewRenderer
from .quality import QualityScorer
from .selection import SelectionReader, SelectionTemplateWriter

logger = get_logger(__name__)

# HTTP 回應用的字元集與內容型別
_CHARSET: str = "utf-8"
_CONTENT_TYPE_HTML: str = "text/html; charset=utf-8"
_CONTENT_TYPE_JSON: str = "application/json; charset=utf-8"
_DEFAULT_MEDIA_TYPE: str = "application/octet-stream"

_INDEX_CSS: str = """
body { font-family: system-ui, "Noto Sans CJK TC", sans-serif; margin: 24px; background: #fafafa; }
h1 { font-size: 20px; }
table { border-collapse: collapse; width: 100%; background: #fff; }
th, td { border: 1px solid #e2e2e2; padding: 8px 10px; text-align: left; font-size: 14px; }
th { background: #1f2937; color: #fff; }
a { color: #2563eb; text-decoration: none; }
.muted { color: #999; }
"""


class _SelectionServer(ThreadingHTTPServer):
    """承載策展情境與共用元件的 server（handler 透過 ``self.server`` 取用）。"""

    daemon_threads = True  # 程式結束時不被殘留連線卡住

    def __init__(self, address: tuple[str, int], context: BuildContext) -> None:
        """以位址與策展情境建構，並預備各組查表與共用元件。"""
        super().__init__(address, _SelectionRequestHandler)
        self.context = context
        self.groups: dict[str, GroupSpec] = {g.group_id: g for g in context.spec.groups}
        self.scorer = QualityScorer()
        self.renderer = InteractivePreviewRenderer()
        self.template_writer = SelectionTemplateWriter()
        self.selection_reader = SelectionReader()

    def ordered_candidates(self, group: GroupSpec) -> list[ClipCandidate]:
        """讀回該組候選、評分後依品質由高到低排序（與互動頁一致）。"""
        candidates = read_models(self.context.candidates_json(group), ClipCandidate)
        # 重建為當前機器的路徑：candidates.json 可能是在別台機器抓的，絕對路徑在此不適用
        candidates = self.context.localized_candidates(group, candidates)
        scored = self.scorer.annotate(candidates)
        return sorted(scored, key=lambda c: c.quality_score or 0.0, reverse=True)


class _SelectionRequestHandler(BaseHTTPRequestHandler):
    """處理互動頁、媒體串流與存檔請求。"""

    server: _SelectionServer  # 型別提示（實際由 ThreadingHTTPServer 注入）

    # ───────────────────────── 路由分派 ─────────────────────────
    # do_GET / do_POST 為 stdlib BaseHTTPRequestHandler 規定的方法名（不可改成 snake_case）
    def do_GET(self) -> None:  # noqa: N802
        """GET 路由：索引／互動頁／媒體串流。"""
        path = unquote(urlparse(self.path).path)
        if path in ("", "/"):
            self._send_html(self._render_index())
        elif path.startswith(SERVER_GROUP_ROUTE + "/"):
            self._handle_group(path[len(SERVER_GROUP_ROUTE) + 1:])
        elif path.startswith(SERVER_WORK_ROUTE + "/"):
            self._serve_media(path[len(SERVER_WORK_ROUTE) + 1:])
        else:
            self._send_text(HTTPStatus.NOT_FOUND, "找不到頁面")

    def do_POST(self) -> None:  # noqa: N802
        """POST 路由：存檔。"""
        path = unquote(urlparse(self.path).path)
        if path.startswith(SERVER_SAVE_ROUTE + "/"):
            self._handle_save(path[len(SERVER_SAVE_ROUTE) + 1:])
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"})

    # ───────────────────────── 各路由處理 ─────────────────────────
    def _render_index(self) -> str:
        """組出各組索引頁：候選數、現有選取數與連結。"""
        ctx = self.server.context
        rows: list[str] = []
        for group in ctx.spec.groups:
            candidates = read_models(ctx.candidates_json(group), ClipCandidate)
            selected = self.server.selection_reader.read(ctx.selection_file(group))
            link = f"{SERVER_GROUP_ROUTE}/{group.group_id}"
            cand_cell = str(len(candidates)) if candidates else "<span class='muted'>0（先跑 fetch）</span>"
            rows.append(
                "<tr>"
                f"<td><a href='{html.escape(link)}'>{html.escape(group.group_id)}</a></td>"
                f"<td>{html.escape(group.theme)}</td>"
                f"<td>{html.escape(group.scope or '-')}</td>"
                f"<td>{cand_cell}</td>"
                f"<td>{len(selected)}</td>"
                "</tr>"
            )
        table = (
            "<table><thead><tr><th>group_id</th><th>主題</th><th>scope</th>"
            "<th>候選</th><th>已選</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        return (
            "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>策展索引</title><style>{_INDEX_CSS}</style></head>"
            f"<body><h1>互動策展索引（共 {len(ctx.spec.groups)} 組）</h1>{table}</body></html>"
        )

    def _handle_group(self, group_id: str) -> None:
        """渲染單組互動頁（候選不存在則提示先跑 fetch）。"""
        group = self.server.groups.get(group_id)
        if group is None:
            self._send_text(HTTPStatus.NOT_FOUND, f"找不到組：{group_id}")
            return
        ctx = self.server.context
        ordered = self.server.ordered_candidates(group)
        if not ordered:
            self._send_html(
                f"<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;margin:24px'>"
                f"<h1>{html.escape(group_id)}</h1><p>尚無候選，請先執行 "
                f"<code>python -m eval -c &lt;spec&gt; fetch</code>。</p>"
                f"<p><a href='/'>← 返回索引</a></p></body>"
            )
            return
        selected_keys = self.server.selection_reader.read(ctx.selection_file(group))
        page = self.server.renderer.render(
            group,
            ordered,
            ctx.resolved_target_seconds(group),
            selected_keys,
            ctx.work_dir,
        )
        self._send_html(page)

    def _serve_media(self, rel_path: str) -> None:
        """串流 work_dir 底下的媒體檔；阻擋目錄遍歷。"""
        work_dir = self.server.context.work_dir.resolve()
        target = (work_dir / rel_path).resolve()
        # 內含防護：解析後路徑必須仍位於 work_dir 之下
        if work_dir not in target.parents or not target.is_file():
            self._send_text(HTTPStatus.NOT_FOUND, "找不到媒體")
            return
        content_type = mimetypes.guess_type(target.name)[0] or _DEFAULT_MEDIA_TYPE
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        with target.open("rb") as fh:
            while chunk := fh.read(DOWNLOAD_CHUNK_SIZE):
                self.wfile.write(chunk)

    def _handle_save(self, group_id: str) -> None:
        """依 POST 的選取清單覆寫該組選取檔。"""
        group = self.server.groups.get(group_id)
        if group is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown group"})
            return
        payload = self._read_json_body()
        if payload is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid json"})
            return

        ctx = self.server.context
        ordered = self.server.ordered_candidates(group)
        valid_keys = {c.cache_key for c in ordered}
        # 只接受確實存在於候選中的 cache_key（忽略未知值）
        selected = {k for k in payload.get("selected", []) if k in valid_keys}
        self.server.template_writer.write_selection(
            ctx.selection_file(group), group, ordered, ctx.resolved_target_seconds(group), selected
        )
        self._send_json(HTTPStatus.OK, {"ok": True, "count": len(selected)})

    # ───────────────────────── 回應小工具 ─────────────────────────
    def _read_json_body(self) -> dict | None:
        """讀取並解析 JSON 請求主體；失敗回 None。"""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode(_CHARSET))
        except (ValueError, UnicodeDecodeError):
            return None

    def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        """回傳 HTML。"""
        self._send_bytes(status, _CONTENT_TYPE_HTML, body.encode(_CHARSET))

    def _send_json(self, status: HTTPStatus, obj: dict) -> None:
        """回傳 JSON。"""
        self._send_bytes(status, _CONTENT_TYPE_JSON, json.dumps(obj, ensure_ascii=False).encode(_CHARSET))

    def _send_text(self, status: HTTPStatus, message: str) -> None:
        """回傳純文字錯誤訊息（包成極簡 HTML）。"""
        self._send_html(f"<!doctype html><meta charset='utf-8'><p>{html.escape(message)}</p>", status)

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        """寫出狀態列、標頭與內容。"""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        """把預設的存取 log 導到本工具的 logger（DEBUG），避免污染 stderr。"""
        logger.debug("%s - %s", self.address_string(), fmt % args)


def run_selection_server(context: BuildContext, host: str, port: int) -> None:
    """啟動互動策展 server，阻塞至 Ctrl-C。"""
    server = _SelectionServer((host, port), context)
    base = f"http://{host}:{port}"
    logger.info("互動策展 server 已啟動：%s/ （Ctrl-C 結束）", base)
    for group in context.spec.groups:
        logger.info("  組 %s → %s%s/%s", group.group_id, base, SERVER_GROUP_ROUTE, group.group_id)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中斷，關閉 server…")
    finally:
        server.server_close()
