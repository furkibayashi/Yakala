"""Takip: kanal, oynatma listesi ve profillerdeki yeni videoları bulur.

Her takip için görülen video kimlikleri saklanır. İlk eklemede mevcut videolar
"görüldü" sayılır; sonraki denetimlerde listede yeni beliren videolar ya otomatik
olarak kuyruğa eklenir ya da "yeni" olarak bekletilir.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from urllib.parse import urlparse

import yt_dlp

from . import config, platforms, tools

SCAN_LIMIT = 30          # her denetimde bakılan son video sayısı
SEEN_LIMIT = 3000
PENDING_LIMIT = 200
INTERVALS = {"30", "60", "180", "360", "1440"}

_YT_CHANNEL = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$", re.I)


class SubError(Exception):
    pass


def _candidates(url: str) -> list[str]:
    """Kanal ana sayfası verildiyse önce 'Videolar' sekmesini dene."""
    p = urlparse(url)
    if platforms.detect(url) == "youtube" and _YT_CHANNEL.match(p.path or ""):
        base = url.split("?")[0].rstrip("/")
        return [base + "/videos", base + "/shorts", url]
    return [url]


def _thumb(e: dict) -> str | None:
    if e.get("thumbnail"):
        return e["thumbnail"]
    th = [t for t in (e.get("thumbnails") or []) if t.get("url")]
    if not th:
        return None
    sized = [t for t in th if t.get("width")]
    return (min(sized, key=lambda t: abs(t["width"] - 360)) if sized else th[-1])["url"]


def fetch(url: str, s: dict) -> dict:
    from .engine import _common_args, _opts, _Logger

    last = "Liste alınamadı."
    for cand in _candidates(url):
        log = _Logger()
        opts = _opts(_common_args(s) + ["--flat-playlist", "--yes-playlist", "--skip-download",
                                        "--playlist-end", str(SCAN_LIMIT)])
        opts.update(logger=log, quiet=True, no_warnings=True, noprogress=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.sanitize_info(ydl.extract_info(cand, download=False))
        except Exception as e:  # noqa: BLE001
            last = log.errors[-1] if log.errors else str(e)
            continue
        if not info or info.get("_type") not in ("playlist", "multi_video") and info.get("entries") is None:
            last = "Bu bağlantı bir kanal, oynatma listesi ya da profil değil."
            continue
        entries = []
        for e in list(info.get("entries") or [])[:SCAN_LIMIT]:
            if not e or not e.get("id"):
                continue
            if e.get("_type") == "url" and e.get("ie_key") in ("YoutubeTab",):
                continue  # sekme bağlantıları, video değil
            entries.append({
                "id": str(e["id"]),
                "url": e.get("url") or e.get("webpage_url") or "",
                "title": e.get("title") or "Başlıksız",
                "duration": e.get("duration"),
                "thumb": _thumb(e),
                "ts": e.get("timestamp"),
            })
        if not entries:
            last = "Bu listede video bulunamadı."
            continue
        title = re.sub(r"\s+-\s+(Videos|Shorts|Videolar)$", "", info.get("title") or "")
        return {
            "url": cand,
            "title": title or info.get("uploader") or info.get("channel") or cand,
            "uploader": info.get("uploader") or info.get("channel") or "",
            "entries": entries,
        }
    plat = platforms.detect(url)
    if plat in ("instagram", "twitter"):
        raise SubError(f"{platforms.NAMES[plat]} profillerini takip etmek henüz desteklenmiyor; "
                       "YouTube kanalları, oynatma listeleri ve TikTok profilleri takip edilebilir.")
    raise SubError(tools.friendly_error(last))


class Subscriptions:
    def __init__(self, engine, settings: config.Settings, thumbs: tools.ThumbCache):
        self.engine = engine
        self.settings = settings
        self.thumbs = thumbs
        self.store = config.JsonStore(config.app_dir() / "subscriptions.json", [])
        self.lock = threading.RLock()
        self.checking: set[str] = set()
        self.events: list[dict] = []   # arayüze bildirilecek yeni video olayları
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------------ yardımcı
    def _get(self, sid: str) -> dict | None:
        return next((x for x in self.store.data if x.get("id") == sid), None)

    def public(self) -> list[dict]:
        with self.lock:
            out = []
            for sub in self.store.data:
                pend = [{**p, "thumb": self.thumbs.register(p.get("thumb"))} for p in sub.get("pending", [])]
                out.append({
                    "id": sub["id"], "url": sub["url"], "title": sub.get("title"), "uploader": sub.get("uploader"),
                    "platform": sub.get("platform"), "mode": sub.get("mode"), "quality": sub.get("quality"),
                    "auto": sub.get("auto"), "last_check": sub.get("last_check"), "error": sub.get("error", ""),
                    "thumb": self.thumbs.register(sub.get("thumb")), "pending": pend,
                    "downloaded": sub.get("downloaded", 0), "checking": sub["id"] in self.checking,
                    "created": sub.get("created"),
                })
            return out

    def take_events(self) -> list[dict]:
        with self.lock:
            ev, self.events = self.events, []
            return ev

    # ------------------------------------------------------------------ işlemler
    def add(self, url: str, mode: str, quality: str, auto: bool) -> dict:
        url = platforms.normalize(url)
        with self.lock:
            for sub in self.store.data:
                if sub["url"] == url or sub.get("source_url") == url:
                    raise SubError("Bunu zaten takip ediyorsun.")
        data = fetch(url, self.settings.snapshot())
        sub = {
            "id": uuid.uuid4().hex[:10],
            "source_url": url,
            "url": data["url"],
            "title": data["title"],
            "uploader": data["uploader"],
            "platform": platforms.detect(url),
            "mode": mode if mode in ("video", "audio") else "video",
            "quality": quality if re.fullmatch(r"best|\d{3,4}", str(quality)) else "best",
            "auto": bool(auto),
            "seen": [e["id"] for e in data["entries"]],
            "pending": [],
            "thumb": data["entries"][0]["thumb"],
            "last_check": time.time(),
            "created": time.time(),
            "downloaded": 0,
            "error": "",
        }
        with self.lock:
            self.store.data.insert(0, sub)
            self.store.save()
        return {"id": sub["id"], "title": sub["title"], "count": len(data["entries"])}

    def update(self, sid: str, changes: dict):
        with self.lock:
            sub = self._get(sid)
            if not sub:
                raise SubError("Takip bulunamadı.")
            if "auto" in changes:
                sub["auto"] = bool(changes["auto"])
            if changes.get("mode") in ("video", "audio"):
                sub["mode"] = changes["mode"]
            if re.fullmatch(r"best|\d{3,4}", str(changes.get("quality", ""))):
                sub["quality"] = str(changes["quality"])
            self.store.save()

    def remove(self, sid: str):
        with self.lock:
            self.store.data = [x for x in self.store.data if x.get("id") != sid]
            self.store.save()

    def download(self, sid: str, ids: list[str] | None = None) -> int:
        with self.lock:
            sub = self._get(sid)
            if not sub:
                raise SubError("Takip bulunamadı.")
            chosen = [p for p in sub.get("pending", []) if not ids or p["id"] in ids]
            sub["pending"] = [p for p in sub.get("pending", []) if p not in chosen]
            sub["downloaded"] = sub.get("downloaded", 0) + len(chosen)
            self.store.save()
        for p in reversed(chosen):
            self._enqueue(sub, p)
        return len(chosen)

    def dismiss(self, sid: str, ids: list[str] | None = None):
        with self.lock:
            sub = self._get(sid)
            if sub:
                sub["pending"] = [p for p in sub.get("pending", []) if ids and p["id"] not in ids]
                self.store.save()

    def _enqueue(self, sub: dict, entry: dict):
        try:
            self.engine.submit({"url": entry["url"], "mode": sub["mode"], "quality": sub["quality"]})
        except Exception:  # noqa: BLE001
            pass

    def check(self, sid: str):
        with self.lock:
            if sid in self.checking:
                return
            sub = self._get(sid)
            if not sub:
                return
            self.checking.add(sid)
            url = sub["url"]
        try:
            data = fetch(url, self.settings.snapshot())
            err = ""
        except Exception as e:  # noqa: BLE001
            data, err = None, str(e)
        finally:
            with self.lock:
                self.checking.discard(sid)
        with self.lock:
            sub = self._get(sid)
            if not sub:
                return
            sub["last_check"] = time.time()
            sub["error"] = err
            if data:
                seen = set(sub.get("seen", []))
                new = [e for e in data["entries"] if e["id"] not in seen]
                sub["thumb"] = data["entries"][0]["thumb"] or sub.get("thumb")
                sub["title"] = data["title"] or sub.get("title")
                sub["seen"] = (sub.get("seen", []) + [e["id"] for e in new])[-SEEN_LIMIT:]
                if new:
                    if sub.get("auto"):
                        sub["downloaded"] = sub.get("downloaded", 0) + len(new)
                    else:
                        sub["pending"] = (new + sub.get("pending", []))[:PENDING_LIMIT]
                    self.events.append({"sub": sub["title"], "count": len(new), "auto": bool(sub.get("auto"))})
            self.store.save()
            auto_new = new if data and new and sub.get("auto") else []
        for e in reversed(auto_new):
            self._enqueue(sub, e)

    def check_all(self, only_due: bool = False):
        minutes = int(self.settings.get("sub_interval") or 60)
        now = time.time()
        with self.lock:
            ids = [x["id"] for x in self.store.data
                   if not only_due or now - (x.get("last_check") or 0) >= minutes * 60]
        for sid in ids:
            self.check(sid)

    def _loop(self):
        time.sleep(15)
        while True:
            try:
                self.check_all(only_due=True)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(60)
