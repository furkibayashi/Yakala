"""Telefondan erişim: aynı Wi-Fi ağındaki telefona indirilenleri sunan ikinci sunucu.

Güvenlik:
- Varsayılan olarak kapalıdır; yalnızca Ayarlar'dan açılınca dinler.
- Yalnızca özel ağ (192.168.x, 10.x, 172.16-31.x) ve yerel adreslerden gelen isteklere yanıt verir.
- Her istek gizli bir erişim anahtarı ister (QR kodla gelir, sonra HttpOnly çerezde tutulur).
  Anahtar yenilenince eski telefonların erişimi biter.
- Yalnızca geçmişteki indirmelerin dosyaları sunulur; dosya yolu istemciden alınmaz.
- Çok sayıda hatalı anahtar denemesi yapan adres bir süre engellenir.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import config, platforms

COOKIE = "yakala_k"
MAX_FAILS = 20
BLOCK_SECONDS = 300

mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("audio/ogg", ".opus")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("video/x-matroska", ".mkv")
mimetypes.add_type("image/webp", ".webp")


class _ExclusiveServer(ThreadingHTTPServer):
    """Kapıyı başka bir sürecin (ya da eski sunucunun) paylaşamayacağı şekilde açar."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def lan_addresses() -> list[str]:
    """Bu bilgisayarın yerel ağdaki IPv4 adresleri (en olası olan başta)."""
    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # paket gönderilmez; yalnızca yönlendirme tablosuna bakılır
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if _private(ip) and not ip.startswith("127.")]


def _private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local


def _kind(path: str) -> str:
    t = mimetypes.guess_type(path)[0] or ""
    return "video" if t.startswith("video/") else "audio" if t.startswith("audio/") else \
        "image" if t.startswith("image/") else "text" if path.lower().endswith(".txt") else "file"


class LanShare:
    def __init__(self, app):
        self.app = app
        self.srv: ThreadingHTTPServer | None = None
        self.port = 0
        self.error = ""
        self.lock = threading.Lock()
        self.fails: dict[str, list] = {}
        self.clients: dict[str, float] = {}
        self.web = config.resource_dir() / "web"

    # ------------------------------------------------------------------ ayarlar
    @property
    def key(self) -> str:
        k = self.app.settings.get("lan_key")
        if not k or len(k) < 20:
            k = secrets.token_urlsafe(18)
            self.app.settings.update({"lan_key": k})
        return k

    def rotate_key(self):
        self.app.settings.update({"lan_key": secrets.token_urlsafe(18)})
        self.clients.clear()

    def status(self) -> dict:
        ips = lan_addresses()
        url = f"http://{ips[0]}:{self.port}/?k={self.key}" if self.srv and ips else ""
        qr = ""
        if url:
            try:
                import segno

                qr = segno.make(url, error="m").svg_data_uri(scale=6, border=2, dark="#191530", light="#ffffff")
            except Exception:  # noqa: BLE001
                qr = ""
        now = time.time()
        recent = sorted(((ip, t) for ip, t in self.clients.items() if now - t < 3600), key=lambda x: -x[1])
        return {
            "enabled": bool(self.srv), "port": self.port or int(self.app.settings.get("lan_port") or 8787),
            "addresses": ips, "url": url, "qr": qr, "error": self.error,
            "clients": [{"ip": ip, "seen": t} for ip, t in recent],
            "allow_send": bool(self.app.settings.get("lan_allow_send")),
        }

    # ------------------------------------------------------------------ yaşam döngüsü
    def start(self) -> bool:
        with self.lock:
            if self.srv:
                return True
            port = int(self.app.settings.get("lan_port") or 8787)
            try:
                srv = _ExclusiveServer(("0.0.0.0", port), _make_handler(self))
            except OSError as e:
                self.error = (f"{port} numaralı kapı kullanımda. Ayarlardan başka bir kapı seç."
                              if getattr(e, "winerror", None) == 10048 or e.errno in (98, 10048)
                              else f"Sunucu başlatılamadı: {e}")
                return False
            self.srv, self.port, self.error = srv, port, ""
            _ = self.key
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            return True

    def stop(self):
        with self.lock:
            if self.srv:
                srv, self.srv = self.srv, None
                srv.shutdown()      # serve_forever döngüsü bitene kadar bekler (en fazla ~0,5 sn)
                srv.server_close()

    def apply(self):
        """Ayarlara göre başlat/durdur."""
        if self.app.settings.get("lan_enabled"):
            if self.srv and self.port != int(self.app.settings.get("lan_port") or 8787):
                self.stop()
            self.start()
        else:
            self.stop()

    # ------------------------------------------------------------------ erişim denetimi
    def blocked(self, ip: str) -> bool:
        f = self.fails.get(ip)
        return bool(f and f[0] >= MAX_FAILS and time.time() - f[1] < BLOCK_SECONDS)

    def fail(self, ip: str):
        f = self.fails.setdefault(ip, [0, 0.0])
        if time.time() - f[1] > BLOCK_SECONDS:
            f[0] = 0
        f[0] += 1
        f[1] = time.time()

    def valid(self, candidate: str) -> bool:
        return bool(candidate) and hmac.compare_digest(candidate.encode(), self.key.encode())

    # ------------------------------------------------------------------ veri
    def items(self) -> list[dict]:
        out = []
        for e in self.app.history.items():
            files = []
            for i, f in enumerate(e.get("files") or []):
                if os.path.isfile(f):
                    files.append({"i": i, "name": os.path.basename(f), "size": os.path.getsize(f), "kind": _kind(f)})
            if not files:
                continue
            out.append({
                "id": e.get("id"), "title": e.get("title"), "uploader": e.get("uploader"),
                "platform": e.get("platform"), "label": e.get("label"), "date": e.get("date"),
                "size": sum(x["size"] for x in files), "files": files, "thumb": bool(e.get("thumb_file")),
            })
        return out

    def file_of(self, entry_id: str, index: int) -> str | None:
        for e in self.app.history.items():
            if e.get("id") == entry_id:
                files = e.get("files") or []
                if 0 <= index < len(files) and os.path.isfile(files[index]):
                    return files[index]
        return None

    def thumb_of(self, entry_id: str) -> str | None:
        for e in self.app.history.items():
            if e.get("id") == entry_id and e.get("thumb_file"):
                p = config.thumbs_dir() / os.path.basename(e["thumb_file"])
                return str(p) if p.is_file() else None
        return None


def _make_handler(share: LanShare):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Yakala"

        def log_message(self, *a):
            pass

        # ---------------------------------------------------------- yardımcılar
        def _ip(self) -> str:
            return self.client_address[0]

        def _send(self, code, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                       {"Cache-Control": "no-store"})

        def _cookie_key(self) -> str:
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    return v
            return ""

        def _guard(self) -> bool:
            """İstek yerel ağdan mı ve anahtar doğru mu? Değilse yanıtı kendisi gönderir."""
            ip = self._ip()
            if not _private(ip):
                self._send(403, b"forbidden", "text/plain")
                return False
            if share.blocked(ip):
                self._send(429, "Çok fazla hatalı deneme. Birkaç dakika sonra tekrar dene.".encode(),
                           "text/plain; charset=utf-8")
                return False
            u = urlparse(self.path)
            qk = (parse_qs(u.query).get("k") or [""])[0]
            if qk and share.valid(qk):
                share.clients[ip] = time.time()
                # Anahtarı adres çubuğundan kaldır, çereze yaz.
                self.send_response(303)
                self.send_header("Location", u.path or "/")
                self.send_header("Set-Cookie", f"{COOKIE}={qk}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            if share.valid(self._cookie_key()):
                share.clients[ip] = time.time()
                return True
            share.fail(ip)
            if u.path in ("/", "/index.html"):
                self._send(401, (share.web / "mobile-locked.html").read_bytes(), "text/html; charset=utf-8")
            else:
                self._json({"ok": False, "error": "Erişim anahtarı geçersiz."}, 401)
            return False

        # ---------------------------------------------------------- GET
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/m/"):
                name = os.path.basename(u.path)
                if name not in ("mobile.css", "mobile.js", "icon.png", "themes.css"):
                    return self._send(404, b"", "text/plain")
                f = share.web / name
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype.endswith("javascript"):
                    ctype += "; charset=utf-8"
                return self._send(200, f.read_bytes(), ctype, {"Cache-Control": "no-cache"})
            if not self._guard():
                return
            if u.path in ("/", "/index.html"):
                return self._send(200, (share.web / "mobile.html").read_bytes(), "text/html; charset=utf-8",
                                  {"Cache-Control": "no-store",
                                   "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                                   "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                   "font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'"})
            if u.path == "/api/items":
                return self._json({"ok": True, "data": share.items(),
                                   "allow_send": bool(share.app.settings.get("lan_allow_send")),
                                   "pc": socket.gethostname(),
                                   "theme": share.app.settings.get("theme") or "dark"})
            if u.path == "/api/queue":
                jobs = [{"title": j["title"], "status": j["status"], "progress": j["progress"], "stage": j["stage"],
                         "platform": j["platform"]} for j in share.app.engine.list()[:20]]
                return self._json({"ok": True, "data": jobs})
            m = re.fullmatch(r"/t/([0-9a-f]{6,32})", u.path)
            if m:
                p = share.thumb_of(m.group(1))
                if not p:
                    return self._send(404, b"", "text/plain")
                with open(p, "rb") as fh:
                    body = fh.read()
                return self._send(200, body, mimetypes.guess_type(p)[0] or "image/jpeg",
                                  {"Cache-Control": "private, max-age=86400"})
            m = re.fullmatch(r"/f/([0-9a-f]{6,32})/(\d{1,4})", u.path)
            if m:
                p = share.file_of(m.group(1), int(m.group(2)))
                if not p:
                    return self._send(404, "Dosya bulunamadı; taşınmış ya da silinmiş olabilir.".encode(),
                                      "text/plain; charset=utf-8")
                return self._file(p, download=bool(parse_qs(u.query).get("dl")))
            return self._send(404, b"", "text/plain")

        def _file(self, path: str, download: bool):
            size = os.path.getsize(path)
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if ctype.startswith("text/"):
                ctype += "; charset=utf-8"
            name = os.path.basename(path)
            disp = ("attachment" if download else "inline") + f"; filename*=UTF-8''{quote(name)}"
            start, end = 0, size - 1
            rng = self.headers.get("Range")
            code = 200
            if rng:
                m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
                if not m or (not m.group(1) and not m.group(2)):
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end or start >= size:
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                code = 206
            length = end - start + 1
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", disp)
            self.send_header("Cache-Control", "private, no-transform")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with open(path, "rb") as fh:
                    fh.seek(start)
                    left = length
                    while left > 0:
                        chunk = fh.read(min(256 * 1024, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (ConnectionError, OSError):
                pass  # telefon oynatmayı durdurdu ya da sardı

        # ---------------------------------------------------------- POST
        def do_POST(self):
            if not self._guard():
                return
            if self.headers.get("X-Yakala") != "1":   # çapraz site isteklerine karşı
                return self._json({"ok": False, "error": "Geçersiz istek."}, 400)
            u = urlparse(self.path)
            if u.path != "/api/send":
                return self._json({"ok": False, "error": "Bulunamadı."}, 404)
            if not share.app.settings.get("lan_allow_send"):
                return self._json({"ok": False, "error": "Telefondan bağlantı gönderme bilgisayarda kapalı."}, 403)
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 100_000)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                return self._json({"ok": False, "error": "Geçersiz istek."}, 400)
            urls = platforms.extract_urls(str(body.get("text") or ""))[:20]
            if not urls:
                return self._json({"ok": False, "error": "Gönderilen metinde bağlantı bulunamadı."})
            mode = "audio" if body.get("mode") == "audio" else "video"
            jobs = [share.app.engine.submit({"url": url, "mode": mode}) for url in urls]
            return self._json({"ok": True, "data": len(jobs)})

    return Handler
