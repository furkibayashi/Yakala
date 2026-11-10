"""Yerel HTTP sunucusu: arayüz dosyaları + JSON API (yalnızca 127.0.0.1)."""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, platforms, tools
from .engine import AnalyzeError, Engine

TOKEN = secrets.token_urlsafe(24)


class App:
    def __init__(self):
        self.settings = config.Settings()
        self.history = config.History()
        self.thumbs = tools.ThumbCache()
        self.engine = Engine(self.settings, self.history, self.thumbs)
        self.web = config.resource_dir() / "web"
        self.window = None  # pywebview penceresi (varsa)

    # ------------------------------------------------------------------ API
    def api(self, name: str, body: dict):
        e = self.engine
        if name == "bootstrap":
            return {
                "settings": self.settings.snapshot(),
                "version": config.APP_VERSION,
                "system": self.system_info(),
            }
        if name == "detect":
            return [platforms.describe(u) for u in platforms.extract_urls(body.get("text", ""))]
        if name == "analyze":
            urls = platforms.extract_urls(body.get("url", ""))
            if not urls:
                raise UserError("Geçerli bir bağlantı bulunamadı.")
            try:
                return e.analyze(urls[0])
            except AnalyzeError as ex:
                raise UserError(str(ex)) from ex
        if name == "download":
            try:
                return e.submit(body)
            except ValueError as ex:
                raise UserError(str(ex)) from ex
        if name == "batch":
            urls = platforms.extract_urls(body.get("text", ""))
            if not urls:
                raise UserError("Geçerli bir bağlantı bulunamadı.")
            mode = "audio" if body.get("mode") == "audio" else "video"
            return [e.submit({"url": u, "mode": mode}) for u in urls[:200]]
        if name == "jobs":
            return {"jobs": e.list(), "ffmpeg": dict(tools.ffmpeg_install), "update": dict(e.update_state)}
        if name == "job":
            return e.action(str(body.get("id")), str(body.get("action")))
        if name == "clear":
            e.clear_finished()
            return True
        if name == "open":
            return tools.open_path(self._resolve_path(body))
        if name == "reveal":
            return tools.reveal_path(self._resolve_path(body))
        if name == "open_folder":
            d = self.settings.get("download_dir")
            os.makedirs(d, exist_ok=True)
            return tools.open_path(d)
        if name == "settings":
            return self.settings.update(body.get("changes") or {})
        if name == "pick_folder":
            return tools.pick_folder(self.settings.get("download_dir"))
        if name == "pick_file":
            return tools.pick_file(self.settings.get("cookies_file"))
        if name == "clipboard":
            text = tools.clipboard_text()
            return {"text": text, "urls": [platforms.describe(u) for u in platforms.extract_urls(text)]}
        if name == "history":
            items = self.history.items()
            for it in items:
                it["exists"] = any(os.path.exists(f) for f in it.get("files") or [])
            return items
        if name == "history_remove":
            self.history.remove(str(body.get("id")))
            return True
        if name == "history_clear":
            self.history.clear()
            return True
        if name == "system":
            return self.system_info()
        if name == "install_ffmpeg":
            tools.install_full_ffmpeg()
            return True
        if name == "update_engines":
            e.update_engines()
            return True
        raise UserError("Bilinmeyen istek.")

    def _resolve_path(self, body: dict) -> str:
        path = body.get("path") or ""
        known = set()
        for j in self.engine.list():
            known.update(j["files"])
        for h in self.history.items():
            known.update(h.get("files") or [])
        known.add(self.settings.get("download_dir"))
        return path if path in known else ""

    def system_info(self) -> dict:
        import gallery_dl.version as gv
        import yt_dlp.version as yv

        ff = tools.ffmpeg_info()
        return {
            "ytdlp": yv.__version__,
            "gallerydl": gv.__version__,
            "ffmpeg": ff,
            "deno": bool(tools.deno_path()),
            "app_dir": str(config.app_dir()),
        }


class UserError(Exception):
    pass


def make_handler(app: App, port_ref: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Yakala"

        def log_message(self, *a):
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            port = port_ref["port"]
            return host in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            u = urlparse(self.path)
            q = parse_qs(u.query)
            path = u.path
            if path in ("/", "/index.html"):
                html = (app.web / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                                  {"Cache-Control": "no-store",
                                   "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                                   "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                   "font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'"})
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                target = (app.web / rel).resolve()
                if app.web.resolve() not in target.parents or not target.is_file():
                    return self._send(404, b"not found", "text/plain")
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype, {"Cache-Control": "no-cache"})
            if (q.get("t") or [""])[0] != TOKEN:
                return self._send(403, b"forbidden", "text/plain")
            if path.startswith("/thumb/"):
                got = app.thumbs.get(path[len("/thumb/"):])
                if not got:
                    return self._send(404, b"", "text/plain")
                body, ctype = got
                return self._send(200, body, ctype, {"Cache-Control": "max-age=86400"})
            if path.startswith("/hthumb/"):
                name = os.path.basename(path[len("/hthumb/"):])
                f = config.thumbs_dir() / name
                if not f.is_file():
                    return self._send(404, b"", "text/plain")
                ctype = mimetypes.guess_type(str(f))[0] or "image/jpeg"
                return self._send(200, f.read_bytes(), ctype, {"Cache-Control": "max-age=86400"})
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
                return self._json(403, {"ok": False, "error": "Yetkisiz istek."})
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._json(404, {"ok": False, "error": "Bulunamadı."})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 2_000_000)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except (ValueError, OSError):
                return self._json(400, {"ok": False, "error": "Geçersiz istek."})
            try:
                data = app.api(u.path[len("/api/"):], body if isinstance(body, dict) else {})
                return self._json(200, {"ok": True, "data": data})
            except UserError as e:
                return self._json(200, {"ok": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001
                return self._json(200, {"ok": False, "error": tools.friendly_error(str(e))})

    return Handler


def start(app: App, port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    port_ref = {"port": 0}
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port_ref))
    srv.daemon_threads = True
    port_ref["port"] = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port_ref["port"]


def wait_forever():
    while True:
        time.sleep(3600)
