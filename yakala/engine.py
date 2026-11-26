"""İndirme motoru: bağlantı analizi, kuyruk ve indirme işleri.

Videolar yt-dlp ile, fotoğraf/karışık gönderiler (Instagram carousel, hikâyeler,
X fotoğrafları, TikTok fotoğraf slaytları) gallery-dl ile çözülür.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
import uuid
from collections import OrderedDict
from pathlib import Path

import yt_dlp

from . import config, platforms, tools, updater

STD_RES = [4320, 2160, 1440, 1080, 720, 480, 360, 240, 144]
VIDEO_EXTS = {"mp4", "mov", "webm", "m4v", "mkv", "m3u8", "gif"}
PLATFORM_FOLDERS = {"youtube": "YouTube", "twitter": "X", "tiktok": "TikTok", "instagram": "Instagram", "other": "Diğer"}
PP_STAGES = {
    "Merger": "Görüntü ve ses birleştiriliyor",
    "FFmpegMerger": "Görüntü ve ses birleştiriliyor",
    "ExtractAudio": "Ses dönüştürülüyor",
    "FFmpegExtractAudio": "Ses dönüştürülüyor",
    "EmbedThumbnail": "Kapak görseli ekleniyor",
    "ThumbnailsConvertor": "Kapak görseli hazırlanıyor",
    "FFmpegThumbnailsConvertor": "Kapak görseli hazırlanıyor",
    "Metadata": "Bilgiler yazılıyor",
    "FFmpegMetadata": "Bilgiler yazılıyor",
    "EmbedSubtitle": "Altyazı ekleniyor",
    "FFmpegEmbedSubtitle": "Altyazı ekleniyor",
    "VideoRemuxer": "Dosya biçimi düzenleniyor",
    "FFmpegVideoRemuxer": "Dosya biçimi düzenleniyor",
    "FixupM3u8": "Dosya onarılıyor",
    "FFmpegFixupM3u8": "Dosya onarılıyor",
}


class Cancelled(Exception):
    pass


class AnalyzeError(Exception):
    pass


class _Logger:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.warnings.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))


# --------------------------------------------------------------------------- #
# Ortak yardımcılar
# --------------------------------------------------------------------------- #
def _cookie_args_ytdl(s: dict) -> list[str]:
    if s.get("cookies_mode") == "browser":
        return ["--cookies-from-browser", s.get("cookies_browser") or "firefox"]
    if s.get("cookies_mode") == "file" and s.get("cookies_file") and os.path.isfile(s["cookies_file"]):
        return ["--cookies", s["cookies_file"]]
    return []


def _cookie_args_gdl(s: dict) -> list[str]:
    if s.get("cookies_mode") == "browser":
        return ["--cookies-from-browser", s.get("cookies_browser") or "firefox"]
    if s.get("cookies_mode") == "file" and s.get("cookies_file") and os.path.isfile(s["cookies_file"]):
        return ["-C", s["cookies_file"]]
    return []


def _common_args(s: dict) -> list[str]:
    a = [
        "--windows-filenames", "--no-mtime", "--no-colors",
        "--socket-timeout", "20", "--retries", "5", "--fragment-retries", "10",
        "--concurrent-fragments", "4",
    ]
    ff = tools.ffmpeg_info()
    if ff["dir"]:
        a += ["--ffmpeg-location", ff["dir"]]
    deno = tools.deno_path()
    if deno:
        a += ["--js-runtimes", f"deno:{deno}"]
    a += _cookie_args_ytdl(s)
    if (s.get("rate_limit") or "").strip():
        a += ["--limit-rate", s["rate_limit"].strip()]
    if (s.get("proxy") or "").strip():
        a += ["--proxy", s["proxy"].strip()]
    return a


def _opts(args: list[str]) -> dict:
    return yt_dlp.parse_options(args).ydl_opts


def _pick_thumb(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    if not thumbs:
        return None
    sized = [t for t in thumbs if t.get("width")]
    if sized:
        return min(sized, key=lambda t: abs((t.get("width") or 0) - 480))["url"]
    return thumbs[-1]["url"]


def _bucket(p: int) -> int:
    for s in STD_RES:
        if abs(p - s) <= s * 0.04:
            return s
    return p


def _fsize(f: dict | None, duration) -> float:
    if not f:
        return 0
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 1000 / 8 * duration
    return float(size or 0)


def _sanitize(name: str, limit: int = 140) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" .")
    return (name[:limit].rstrip(" .") or "dosya")


def _dig(d: dict, *paths):
    for path in paths:
        cur = d
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, "", [], {}):
            return cur
    return None


SIZE_LIMITS = (10, 25, 50)


def fit_format(formats: list[dict], duration, limit_mb: int, lang: str | None = None,
               prefer_h264: bool = True) -> dict | None:
    """Verilen boyuta sığan en yüksek çözünürlüklü görüntü+ses birleşimini seçer."""
    limit = limit_mb * 1024 * 1024 * 0.96
    vids = [f for f in formats if f.get("vcodec") != "none" and (f.get("width") or f.get("height"))]
    auds = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    if lang:
        auds = [a for a in auds if a.get("language") == lang] or auds
    best = None
    for v in vids:
        vs = _fsize(v, duration)
        if not vs:
            continue
        combos = []
        if v.get("acodec") != "none":
            combos.append((v["format_id"], vs))
        else:
            for a in auds:
                asz = _fsize(a, duration)
                if asz:
                    combos.append((f"{v['format_id']}+{a['format_id']}", vs + asz))
        res = min(x for x in (v.get("width"), v.get("height")) if x)
        h264 = str(v.get("vcodec") or "").startswith(("avc", "h264"))
        for spec, size in combos:
            if size <= limit:
                key = (res, h264 if prefer_h264 else False, size)
                if best is None or key > best[0]:
                    best = (key, spec, size, res)
    if not best:
        return None
    return {"spec": best[1], "size": int(best[2]), "res": _bucket(best[3])}


def _caption_text(title: str, owner: str, url: str, date: str, body: str, tags=None) -> str:
    lines = [f"Başlık: {title}" if title else "", f"Hesap: {owner}" if owner else "",
             f"Bağlantı: {url}" if url else "", f"Tarih: {date}" if date else ""]
    out = "\n".join(x for x in lines if x)
    if body:
        out += "\n\n" + body.strip()
    if tags:
        out += "\n\n" + " ".join("#" + str(t).lstrip("#") for t in tags if t)
    return out + "\n"


def write_caption(path: str, text: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Analiz
# --------------------------------------------------------------------------- #
def _ytdl_extract(url: str, s: dict) -> dict:
    log = _Logger()
    opts = _opts(_common_args(s) + ["--flat-playlist", "--no-playlist", "--skip-download"])
    opts.update(logger=log, quiet=True, no_warnings=True, noprogress=True, skip_download=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:  # noqa: BLE001
            raise AnalyzeError(log.errors[-1] if log.errors else str(e)) from e
        if not info:
            raise AnalyzeError(log.errors[-1] if log.errors else "İçerik bulunamadı.")
        return ydl.sanitize_info(info)


def _from_ytdl(info: dict, desc: dict, thumbs: tools.ThumbCache) -> dict:
    base = {
        "title": info.get("title") or info.get("fulltitle") or "Başlıksız",
        "uploader": info.get("uploader") or info.get("channel") or info.get("creator") or "",
        "thumb": thumbs.register(_pick_thumb(info)),
        "source": "ytdlp",
        **desc,
    }
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries") is not None:
        entries = []
        for i, e in enumerate(list(info.get("entries") or []), 1):
            if not e:
                continue
            entries.append({
                "index": i,
                "title": e.get("title") or f"Öğe {i}",
                "duration": e.get("duration"),
                "uploader": e.get("uploader") or e.get("channel") or "",
                "thumb": thumbs.register(_pick_thumb(e)),
            })
            if len(entries) >= 2000:
                break
        if not base["thumb"] and entries:
            base["thumb"] = entries[0]["thumb"]
        return {**base, "type": "playlist", "count": len(entries), "entries": entries}

    duration = info.get("duration")
    fmts = [f for f in (info.get("formats") or [info]) if f.get("ext") != "mhtml"
            and "storyboard" not in str(f.get("format_note") or "").lower()]
    audio = [f for f in fmts if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max(audio, key=lambda f: (f.get("abr") or f.get("tbr") or 0), default=None)
    audio_size = _fsize(best_audio, duration)
    buckets: dict[int, dict] = {}
    for f in fmts:
        if f.get("vcodec") == "none":
            continue
        dims = [x for x in (f.get("width"), f.get("height")) if x]
        if not dims:
            continue
        res = _bucket(min(dims))
        size = _fsize(f, duration)
        if f.get("acodec") == "none" and size:
            size += audio_size
        b = buckets.setdefault(res, {"res": res, "size": 0, "fps": 0})
        b["size"] = max(b["size"], size)
        b["fps"] = max(b["fps"], int(f.get("fps") or 0))
    qualities = sorted(buckets.values(), key=lambda b: -b["res"])
    langs: dict[str, dict] = {}
    for f in audio:
        lang = f.get("language")
        if not lang or not re.fullmatch(r"[\w-]{2,12}", str(lang)):
            continue
        ent = langs.setdefault(lang, {"code": lang, "size": 0, "original": False})
        ent["size"] = max(ent["size"], _fsize(f, duration))
        if "original" in str(f.get("format_note") or "").lower() or (f.get("language_preference") or 0) >= 10:
            ent["original"] = True
    audio_langs = sorted(langs.values(), key=lambda x: (not x["original"], x["code"])) if len(langs) > 1 else []
    slim = [{k: f.get(k) for k in ("format_id", "vcodec", "acodec", "width", "height", "filesize",
                                    "filesize_approx", "tbr", "language", "ext")} for f in fmts if f.get("format_id")]
    fits = {}
    if duration and qualities:
        for mb in SIZE_LIMITS:
            got = fit_format(slim, duration, mb)
            if got:
                fits[str(mb)] = {"res": got["res"], "size": got["size"]}
    chapters = [{"title": c.get("title") or f"Bölüm {i}", "start": c.get("start_time"), "end": c.get("end_time")}
                for i, c in enumerate(info.get("chapters") or [], 1) if c.get("start_time") is not None]
    has_video = bool(qualities) or any(f.get("vcodec") not in ("none",) for f in fmts if f.get("vcodec"))
    if not audio_size and qualities:
        audio_size = (duration or 0) * 160_000 / 8
    date = info.get("upload_date")
    return {
        **base,
        "type": "video",
        "has_video": has_video,
        "duration": duration,
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "date": f"{date[6:8]}.{date[4:6]}.{date[:4]}" if date and len(date) == 8 else "",
        "qualities": qualities,
        "audio_size": audio_size,
        "subtitles": sorted((info.get("subtitles") or {}).keys())[:40],
        "is_live": bool(info.get("is_live")),
        "chapters": chapters[:200],
        "audio_langs": audio_langs,
        "size_fits": fits,
        "sponsorblock": desc.get("platform") == "youtube",
        "_formats": slim,
    }


def _gallery_extract(url: str, s: dict, thumbs: tools.ThumbCache) -> tuple[dict, list[dict]]:
    cmd = tools.helper_cmd("--gallery-dl", "-J", "--range", "1-400", *_cookie_args_gdl(s), url)
    if (s.get("proxy") or "").strip():
        cmd[-1:-1] = ["--proxy", s["proxy"].strip()]
    try:
        r = tools.run_hidden(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150)
    except Exception as e:  # noqa: BLE001
        raise AnalyzeError(f"gallery-dl çalıştırılamadı: {e}") from e
    out = (r.stdout or "").strip()
    err_lines = [ln for ln in (r.stderr or "").splitlines() if "[error]" in ln.lower() or "error" in ln.lower()]
    try:
        data = json.loads(out) if out else []
    except ValueError:
        data = []
    media: list[tuple[str, dict]] = []
    errors: list[str] = []
    meta: dict = {}

    def walk(msgs):
        for m in msgs or []:
            if not isinstance(m, list) or not m:
                continue
            if isinstance(m[0], list):
                walk(m)
                continue
            t = m[0]
            if t == -1 and len(m) > 1 and isinstance(m[1], dict):
                errors.append(m[1].get("message") or m[1].get("error") or "Hata")
            elif t == 2 and len(m) > 1 and isinstance(m[1], dict):
                if not meta:
                    meta.update(m[1])
            elif t == 3 and len(m) > 2 and isinstance(m[1], str):
                media.append((m[1], m[2] if isinstance(m[2], dict) else {}))
            elif t == 6 and len(m) > 2 and isinstance(m[2], list):
                walk(m[2])

    walk(data if isinstance(data, list) else [])
    if not media:
        msg = (errors[-1] if errors else (err_lines[-1] if err_lines else "Bu bağlantıda indirilebilir medya bulunamadı."))
        raise AnalyzeError(msg)

    items, internal = [], []
    for i, (murl, kw) in enumerate(media, 1):
        ext = str(kw.get("extension") or "").lower() or (murl.rsplit(".", 1)[-1].split("?")[0].lower()[:5] or "jpg")
        if murl.startswith("ytdl:"):
            ext = "mp4"
        is_video = ext in VIDEO_EXTS or murl.startswith("ytdl:")
        owner = _dig(kw, "username", "owner_id", "author.name", "author.uniqueId", "author.nick",
                     "user.name", "user.username", "uploader", "nick") or ""
        post = _dig(kw, "post_shortcode", "shortcode", "tweet_id", "post_id", "id", "media_id") or ""
        num = kw.get("num") or i
        stem = _sanitize(f"{owner}_{post}_{num}" if owner and post else (kw.get("filename") or f"medya_{i}"), 120)
        thumb_src = murl if not is_video else _dig(kw, "display_url", "thumbnail", "thumbnail_url", "cover",
                                                    "image", "preview", "poster")
        if isinstance(thumb_src, str) and thumb_src.startswith("ytdl:"):
            thumb_src = None
        items.append({
            "index": i,
            "kind": "video" if is_video else "image",
            "ext": ext,
            "width": kw.get("width"),
            "height": kw.get("height"),
            "thumb": thumbs.register(thumb_src if isinstance(thumb_src, str) else None),
        })
        caption = _dig(kw, "description", "content", "desc", "caption", "title") or ""
        internal.append({"url": murl, "stem": stem, "ext": ext, "kind": "video" if is_video else "image",
                         "owner": str(owner), "post": str(post), "caption": str(caption),
                         "date": str(kw.get("date") or ""), "tags": kw.get("tags") or kw.get("hashtags") or []})

    first = media[0][1]
    title = _dig(first, "description", "content", "desc", "title", "caption") or _dig(meta, "description", "content", "title") or ""
    title = re.sub(r"https?://t\.co/\S+", "", str(title))
    title = re.sub(r"\s+", " ", title).strip()
    owner = _dig(first, "username", "author.name", "author.uniqueId", "user.name", "uploader") or ""
    if not title:
        title = f"{owner} gönderisi" if owner else "Medya galerisi"
    images = sum(1 for it in items if it["kind"] == "image")
    result = {
        "type": "gallery",
        "title": title[:300],
        "uploader": str(owner),
        "thumb": next((it["thumb"] for it in items if it["thumb"]), None),
        "items": items,
        "count": len(items),
        "images": images,
        "videos": len(items) - images,
        "truncated": len(items) >= 400,
        "source": "gallery-dl",
    }
    return result, internal


def _is_login_error(msg: str) -> bool:
    return tools.friendly_error(msg).endswith(tools.LOGIN_HINT)


def analyze(url: str, s: dict, thumbs: tools.ThumbCache) -> tuple[dict, list[dict]]:
    """(sonuç, dahili medya listesi) döner. Hata durumunda AnalyzeError."""
    url = platforms.normalize(url)
    desc = platforms.describe(url)
    plat, kind = desc["platform"], desc["kind"]
    gallery_first = (plat == "instagram" and kind in ("story", "highlight", "profile")) or (plat == "tiktok" and kind == "photo")
    errors: list[str] = []

    def try_gallery():
        res, internal = _gallery_extract(url, s, thumbs)
        return {**desc, **res, "url": url}, internal

    if not gallery_first:
        try:
            res = _from_ytdl(_ytdl_extract(url, s), desc, thumbs)
            res["url"] = url
            if res["type"] == "playlist" and plat in ("instagram", "twitter", "tiktok"):
                try:
                    return try_gallery()
                except AnalyzeError:
                    pass
            return res, []
        except AnalyzeError as e:
            errors.append(str(e))
    try:
        return try_gallery()
    except AnalyzeError as e:
        errors.append(str(e))
    if gallery_first:
        try:
            res = _from_ytdl(_ytdl_extract(url, s), desc, thumbs)
            res["url"] = url
            return res, []
        except AnalyzeError as e:
            errors.append(str(e))
    no_video = re.compile(r"no video|there.?s no video", re.I)
    useful = [e for e in errors if not no_video.search(e)] or errors
    best = next((e for e in errors if _is_login_error(e)), useful[0] if useful else "Bilinmeyen hata")
    raise AnalyzeError(tools.friendly_error(best))


# --------------------------------------------------------------------------- #
# İşler
# --------------------------------------------------------------------------- #
def _ts(sec) -> str:
    sec = int(sec or 0)
    h, m, x = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def _num(v):
    try:
        f = float(v)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None


class Job:
    def __init__(self, url: str, mode: str, opts: dict, meta: dict | None = None):
        meta = meta or {}
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        d = platforms.describe(url)
        self.platform = meta.get("platform") or d["platform"]
        self.kind_name = meta.get("kind_name") or d["kind_name"]
        self.title = meta.get("title") or url
        self.uploader = meta.get("uploader") or ""
        self.thumb = meta.get("thumb")
        self.mode = mode  # video | audio | gallery
        self.opts = opts
        self.internal: list[dict] = meta.get("_internal") or []
        self.needs_analysis = bool(meta.get("_needs_analysis"))
        self.status = "queued"
        self.stage = "Sırada"
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.done_bytes = 0
        self.total_bytes = 0
        self.item_index = 0
        self.item_count = 0
        self.items_done = 0
        self.files: list[str] = []
        self.parts: set[str] = set()
        self.stems: set[str] = set()
        self.error = ""
        self.warning = ""
        self.created = time.time()
        self.finished = None
        self.cancel_flag = False
        self.pause_flag = False
        self.label = ""
        self.size = 0
        self._update_label()

    def _update_label(self):
        o = self.opts
        if self.mode == "audio":
            q = o.get("audio_quality", "best")
            self.label = f"{o.get('audio_format', 'mp3').upper()}" + ("" if q == "best" or o.get("audio_format") in ("wav", "flac") else f" {q} kbps")
        elif self.mode == "gallery":
            n = len(o.get("items") or []) or len(self.internal)
            self.label = f"{n} medya" if n else "Galeri"
        else:
            q = o.get("quality", "best")
            self.label = ("En iyi kalite" if q == "best" else f"{q}p") + f" {o.get('container', 'mp4').upper()}"
            if o.get("size_limit"):
                self.label = o.get("container", "mp4").upper()
        if o.get("entries"):
            self.label += f", {len(o['entries'])} video"
        if o.get("size_limit"):
            self.label += f", en fazla {o['size_limit']} MB"
        if o.get("clip_start") is not None or o.get("clip_end") is not None:
            end = _ts(o["clip_end"]) if o.get("clip_end") is not None else "son"
            self.label += f", klip {_ts(o.get('clip_start') or 0)}–{end}"
        if o.get("sponsorblock"):
            self.label += ", sponsorsuz"
        if o.get("split_chapters"):
            self.label += ", bölümlere ayrılmış"

    def check(self):
        if self.cancel_flag or self.pause_flag:
            raise Cancelled()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "url": self.url, "platform": self.platform, "kind_name": self.kind_name,
            "title": self.title, "uploader": self.uploader, "thumb": self.thumb, "mode": self.mode,
            "status": self.status, "stage": self.stage, "progress": round(self.progress, 4),
            "speed": self.speed, "eta": self.eta, "done_bytes": self.done_bytes, "total_bytes": self.total_bytes,
            "item_index": self.item_index, "item_count": self.item_count, "files": self.files,
            "error": self.error, "warning": self.warning, "label": self.label,
            "created": self.created, "finished": self.finished, "size": self.size,
            "pausable": self.opts.get("clip_start") is None and self.opts.get("clip_end") is None,
        }


class Engine:
    def __init__(self, settings: config.Settings, history: config.History, thumbs: tools.ThumbCache):
        self.settings = settings
        self.history = history
        self.thumbs = thumbs
        self.jobs: "OrderedDict[str, Job]" = OrderedDict()
        self.analyses: "OrderedDict[str, tuple[dict, list[dict]]]" = OrderedDict()
        self.lock = threading.RLock()

    # ---- analiz ---------------------------------------------------------- #
    def analyze(self, url: str) -> dict:
        res, internal = analyze(url, self.settings.snapshot(), self.thumbs)
        aid = uuid.uuid4().hex[:10]
        with self.lock:
            self.analyses[aid] = (res, internal)
            while len(self.analyses) > 60:
                self.analyses.popitem(last=False)
        public = {k: v for k, v in res.items() if not k.startswith("_")}
        prev = self.history.find(res.get("url"))
        if prev:
            public["previous"] = {"date": prev.get("date"), "label": prev.get("label"),
                                  "file": next((f for f in prev.get("files") or [] if os.path.exists(f)), "")}
        return {**public, "aid": aid}

    # ---- kuyruk ---------------------------------------------------------- #
    def submit(self, req: dict) -> dict:
        s = self.settings.snapshot()
        mode = req.get("mode") if req.get("mode") in ("video", "audio", "gallery") else "video"
        opts = {
            "quality": str(req.get("quality") or s["video_quality"]),
            "container": req.get("container") if req.get("container") in ("mp4", "mkv") else s["video_container"],
            "audio_format": req.get("audio_format") if req.get("audio_format") in config.CHOICES["audio_format"] else s["audio_format"],
            "audio_quality": str(req.get("audio_quality") or s["audio_quality"]),
            "subtitles": bool(req.get("subtitles", s["subtitles"])),
            "entries": [int(i) for i in (req.get("entries") or []) if str(i).isdigit()],
            "items": [int(i) for i in (req.get("items") or []) if str(i).isdigit()],
            "clip_start": _num(req.get("clip_start")),
            "clip_end": _num(req.get("clip_end")),
            "exact_cut": bool(req.get("exact_cut")),
            "sponsorblock": bool(req.get("sponsorblock")),
            "split_chapters": bool(req.get("split_chapters")),
            "audio_lang": req.get("audio_lang") if re.fullmatch(r"[\w-]{2,12}", str(req.get("audio_lang") or "")) else None,
            "size_limit": int(req["size_limit"]) if str(req.get("size_limit")) in {str(x) for x in SIZE_LIMITS} else None,
        }
        if opts["clip_start"] == 0 and opts["clip_end"] is None:
            opts["clip_start"] = None
        if opts["clip_start"] is not None and opts["clip_end"] is not None and opts["clip_end"] <= opts["clip_start"]:
            raise ValueError("Klibin bitişi başlangıcından sonra olmalı.")
        if not re.fullmatch(r"best|\d{2,4}", opts["quality"]):
            opts["quality"] = "best"
        if opts["audio_quality"] not in config.CHOICES["audio_quality"]:
            opts["audio_quality"] = "best"
        meta: dict = {}
        url = platforms.normalize(str(req.get("url") or ""))
        aid = req.get("aid")
        with self.lock:
            cached = self.analyses.get(aid) if aid else None
        if cached:
            res, internal = cached
            url = res["url"]
            meta = {k: res.get(k) for k in ("title", "uploader", "thumb", "platform", "kind_name")}
            meta["_internal"] = internal
            if res["type"] == "gallery":
                mode = "gallery"
            elif res["type"] == "playlist":
                opts["_is_playlist"] = True
            if opts["size_limit"] and mode == "video" and res.get("_formats"):
                got = fit_format(res["_formats"], res.get("duration"), opts["size_limit"], opts["audio_lang"],
                                 bool(s.get("compat_codecs")))
                if not got:
                    raise ValueError(f"Bu video {opts['size_limit']} MB sınırına sığmıyor.")
                opts["format_spec"] = got["spec"]
        elif not url.startswith("http"):
            raise ValueError("Geçerli bir bağlantı gerekli.")
        else:
            meta["_needs_analysis"] = True
        job = Job(url, mode, opts, meta)
        with self.lock:
            self.jobs[job.id] = job
        self._pump()
        return job.to_dict()

    def list(self) -> list[dict]:
        with self.lock:
            return [j.to_dict() for j in reversed(self.jobs.values())]

    def _pump(self):
        with self.lock:
            limit = int(self.settings.get("concurrency") or 2)
            running = sum(1 for j in self.jobs.values() if j.status == "running")
            for job in self.jobs.values():
                if running >= limit:
                    break
                if job.status == "queued":
                    job.status = "running"
                    job.stage = "Hazırlanıyor"
                    running += 1
                    threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def action(self, job_id: str, action: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if action == "cancel":
                if job.status == "running":
                    job.cancel_flag = True
                    job.stage = "İptal ediliyor"
                elif job.status in ("queued", "paused"):
                    job.status, job.stage = "canceled", "İptal edildi"
                    self._cleanup_parts(job)
            elif action == "pause" and job.status in ("running", "queued"):
                if job.status == "running":
                    job.pause_flag = True
                    job.stage = "Duraklatılıyor"
                else:
                    job.status, job.stage = "paused", "Duraklatıldı"
            elif action in ("resume", "retry") and job.status in ("paused", "error", "canceled"):
                job.status, job.stage, job.error = "queued", "Sırada", ""
                job.cancel_flag = job.pause_flag = False
                job.speed = job.eta = None
            elif action == "remove" and job.status != "running":
                if job.status in ("queued", "paused"):
                    self._cleanup_parts(job)
                del self.jobs[job_id]
        self._pump()
        return True

    def clear_finished(self):
        with self.lock:
            for jid in [k for k, j in self.jobs.items() if j.status in ("done", "error", "canceled")]:
                del self.jobs[jid]

    def active_count(self) -> int:
        with self.lock:
            return sum(1 for j in self.jobs.values() if j.status in ("running", "queued"))

    def files_of(self, job_id: str) -> list[str]:
        with self.lock:
            job = self.jobs.get(job_id)
            return list(job.files) if job else []

    @staticmethod
    def _cleanup_parts(job: Job):
        for p in list(job.parts):
            for cand in (p, p + ".part", p + ".ytdl"):
                try:
                    if cand and os.path.isfile(cand) and (cand.endswith((".part", ".ytdl")) or ".part-Frag" in cand):
                        os.remove(cand)
                except OSError:
                    pass
        job.parts.clear()
        for stem in list(job.stems):
            for ext in (".jpg", ".webp", ".png", ".temp.mp4", ".temp.mkv"):
                try:
                    if os.path.isfile(stem + ext):
                        os.remove(stem + ext)
                except OSError:
                    pass
        job.stems.clear()

    # ---- çalıştırma ------------------------------------------------------ #
    def _out_dir(self, job: Job, s: dict) -> Path:
        base = Path(s.get("download_dir") or config.default_download_dir())
        if s.get("platform_folders"):
            base = base / PLATFORM_FOLDERS.get(job.platform, "Diğer")
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _run(self, job: Job):
        s = self.settings.snapshot()
        job.started = time.time()
        try:
            if job.needs_analysis:
                job.stage = "Bağlantı inceleniyor"
                res, internal = analyze(job.url, s, self.thumbs)
                job.title = res.get("title") or job.title
                job.uploader = res.get("uploader") or ""
                job.thumb = res.get("thumb")
                job.kind_name = res.get("kind_name") or job.kind_name
                if res["type"] == "gallery":
                    job.mode = "gallery"
                    job.internal = internal
                elif res["type"] == "playlist":
                    job.opts["_is_playlist"] = True
                job.needs_analysis = False
                job._update_label()
            job.check()
            outdir = self._out_dir(job, s)
            if job.mode == "gallery":
                self._run_gallery(job, s, outdir)
            else:
                self._run_ytdl(job, s, job.url, outdir)
            job.check()
            if not job.files:
                raise RuntimeError("Dosya oluşturulamadı.")
            job.status, job.stage, job.progress = "done", "Tamamlandı", 1.0
            job.finished = time.time()
            job.speed = job.eta = None
            self._record(job)
        except Exception as e:  # noqa: BLE001
            job.speed = job.eta = None
            if job.pause_flag:
                job.status, job.stage = "paused", "Duraklatıldı"
            elif job.cancel_flag:
                job.status, job.stage = "canceled", "İptal edildi"
                self._cleanup_parts(job)
            elif job.files and all(os.path.exists(f) for f in job.files):
                job.status, job.stage, job.progress = "done", "Tamamlandı", 1.0
                job.warning = "Bazı son işlemler yapılamadı: " + tools.friendly_error(str(e))
                job.finished = time.time()
                self._record(job)
            else:
                job.status, job.stage = "error", "Hata"
                job.error = tools.friendly_error(str(e))
                job.finished = time.time()
        finally:
            if job.status != "running":
                job.cancel_flag = job.pause_flag = False
            self._pump()

    def _ytdl_args(self, job: Job, s: dict, outdir: Path, template: str | None = None, force_video=False) -> list[str]:
        o = job.opts
        a = _common_args(s)
        mode = "video" if force_video else job.mode
        if mode == "audio":
            fmt = o["audio_format"]
            lang = o.get("audio_lang")
            a += ["-f", f"ba[language={lang}]/ba/b" if lang else "ba/b", "-x", "--audio-format", fmt]
            q = o["audio_quality"]
            a += ["--audio-quality", "0" if q == "best" or fmt in ("wav", "flac") else f"{q}K"]
            if s.get("embed_thumbnail") and fmt != "wav":
                a += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
        else:
            cont = o["container"]
            q = o["quality"]
            sort = "res" if q == "best" else f"res:{q}"
            if s.get("compat_codecs") and cont == "mp4":
                sort += ",vcodec:h264,acodec:aac"
            lang = o.get("audio_lang")
            vfmt = f"bv*+ba[language={lang}]/bv*+ba/b" if lang else "bv*+ba/b"
            if o.get("format_spec") and not force_video:
                vfmt = o["format_spec"]
            a += ["-f", vfmt, "-S", sort, "--merge-output-format", cont, "--remux-video", cont]
            if s.get("embed_thumbnail"):
                a += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
            if o.get("subtitles"):
                a += ["--write-subs", "--sub-langs", s.get("sub_langs") or "tr,en", "--embed-subs", "--sleep-subtitles", "1"]
        if not force_video:
            if o.get("clip_start") is not None or o.get("clip_end") is not None:
                end = o.get("clip_end")
                a += ["--download-sections", f"*{o.get('clip_start') or 0}-{end if end is not None else 'inf'}"]
                if o.get("exact_cut") or mode == "audio":
                    a += ["--force-keyframes-at-cuts"]
            if o.get("sponsorblock"):
                a += ["--sponsorblock-remove", "sponsor,selfpromo,interaction"]
            if o.get("split_chapters"):
                a += ["--split-chapters", "-o",
                      "chapter:%(title).80B - bölümler/%(section_number)02d - %(section_title).80B.%(ext)s"]
        if s.get("embed_metadata"):
            a += ["--embed-metadata"]
        tmpl = template or config.FILENAME_TEMPLATES.get(s.get("filename"), config.FILENAME_TEMPLATES["title_id"])
        if job.opts.get("_is_playlist") and not force_video:
            tmpl = "%(playlist_title,playlist|Liste).80B/" + tmpl
            a += ["--yes-playlist", "--ignore-errors"]
            if o.get("entries"):
                a += ["-I", ",".join(str(i) for i in sorted(set(o["entries"])))]
        else:
            a += ["--no-playlist"]
        a += ["-P", str(outdir), "-o", tmpl]
        return a

    def _run_ytdl(self, job: Job, s: dict, url: str, outdir: Path, template: str | None = None,
                  force_video=False, frac=None):
        """frac: (başlangıç, genişlik) — galeri içindeki tek bir video için ilerleme dilimi."""
        log = _Logger()
        opts = _opts(self._ytdl_args(job, s, outdir, template, force_video))
        # Klip indirmede yt-dlp ffmpeg konumunu bu bağlam değişkeninden okur (komut satırı onu kendisi ayarlar).
        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
        FFmpegPostProcessor._ffmpeg_location.set(opts.get("ffmpeg_location"))
        state = {"sizes": None}

        def hook(d):
            job.check()
            info = d.get("info_dict") or {}
            if info.get("id"):
                job.last_info = info
            if d.get("status") == "downloading":
                tmp = d.get("tmpfilename") or d.get("filename")
                if tmp:
                    job.parts.add(tmp)
                if d.get("filename"):
                    job.stems.add(re.sub(r"(\.f[\w-]+)?\.\w+$", "", d["filename"]))
                done = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                req = info.get("requested_formats") or []
                part_frac = (done / total) if total else 0
                if len(req) > 1:
                    ids = [f.get("format_id") for f in req]
                    idx = ids.index(info.get("format_id")) if info.get("format_id") in ids else 0
                    sizes = [_fsize(f, info.get("duration")) or 1 for f in req]
                    if total:
                        sizes[idx] = total
                    whole = sum(sizes) or 1
                    item_frac = (sum(sizes[:idx]) + done) / whole
                    is_video = req[idx].get("vcodec") not in (None, "none")
                    job.stage = "Görüntü indiriliyor" if is_video else "Ses indiriliyor"
                    job.total_bytes = int(whole)
                    job.done_bytes = int(sum(sizes[:idx]) + done)
                else:
                    item_frac = part_frac
                    job.stage = "İndiriliyor"
                    job.total_bytes = int(total)
                    job.done_bytes = int(done)
                n = info.get("n_entries") or info.get("playlist_count")
                if job.opts.get("_is_playlist") and n:
                    job.item_count = len(job.opts.get("entries") or []) or n
                    job.item_index = min(job.items_done + 1, job.item_count)
                    job.progress = min(0.999, (job.items_done + item_frac) / job.item_count)
                elif frac:
                    job.progress = min(0.999, frac[0] + frac[1] * item_frac)
                else:
                    job.progress = min(0.999, item_frac * 0.97)
                job.speed = d.get("speed")
                job.eta = d.get("eta")
            elif d.get("status") == "finished":
                job.speed = None
                job.eta = None

        def pp_hook(d):
            job.check()
            if d.get("status") == "started":
                name = d.get("postprocessor") or ""
                job.stage = PP_STAGES.get(name, PP_STAGES.get("FFmpeg" + name, "İşleniyor"))
                job.speed = job.eta = None
            elif d.get("status") == "finished" and "Thumbnail" in str(d.get("postprocessor")) \
                    and not job.opts.get("_clip_started") and (job.opts.get("clip_start") is not None
                                                                or job.opts.get("clip_end") is not None):
                job.opts["_clip_started"] = True
                job.stage = "Klip indirilip kesiliyor"

        def post_hook(filename):
            if filename and filename not in job.files:
                job.files.append(filename)
                info = getattr(job, "last_info", None) or {}
                if s.get("save_caption") and info:
                    d = info.get("upload_date") or ""
                    write_caption(os.path.splitext(filename)[0] + ".txt", _caption_text(
                        info.get("title") or "", info.get("uploader") or info.get("channel") or "",
                        info.get("webpage_url") or url, f"{d[6:8]}.{d[4:6]}.{d[:4]}" if len(d) == 8 else "",
                        info.get("description") or "", info.get("tags") or []))
            job.items_done += 1
            for p in list(job.parts):
                if not os.path.exists(p):
                    job.parts.discard(p)

        opts.update(logger=log, quiet=True, no_warnings=True, noprogress=True,
                    progress_hooks=[hook], postprocessor_hooks=[pp_hook], post_hooks=[post_hook])
        job.stage = "Bağlanıyor"
        before = len(job.files)
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                ydl.download([url])
            except Exception as e:  # noqa: BLE001
                job.check()
                if len(job.files) > before and job.opts.get("_is_playlist"):
                    job.warning = f"Bazı videolar indirilemedi: {tools.friendly_error(str(e))}"
                    return
                raise RuntimeError(log.errors[-1] if log.errors else str(e)) from e
        job.check()
        if len(job.files) == before:
            raise RuntimeError(log.errors[-1] if log.errors else "İndirilecek dosya bulunamadı.")
        if job.opts.get("split_chapters") and not force_video:
            for d in sorted(outdir.iterdir()):
                if d.is_dir() and d.name.endswith(" - bölümler") and d.stat().st_mtime >= job.started - 2:
                    job.files.extend(str(f) for f in sorted(d.iterdir()) if f.is_file() and str(f) not in job.files)
        if log.errors and job.opts.get("_is_playlist"):
            failed = len(log.errors)
            job.warning = f"{failed} öğe indirilemedi: {tools.friendly_error(log.errors[-1])}"

    def _run_gallery(self, job: Job, s: dict, outdir: Path):
        internal = job.internal
        chosen = set(job.opts.get("items") or [])
        items = [it for i, it in enumerate(internal, 1) if not chosen or i in chosen]
        if not items:
            raise RuntimeError("Seçili medya yok.")
        job.item_count = len(items)
        n = len(items)
        for i, it in enumerate(items):
            job.check()
            job.item_index = i + 1
            if it["url"].startswith("ytdl:") or (it["kind"] == "video" and it["url"].startswith("ytdl")):
                self._run_ytdl(job, s, it["url"][5:], outdir, template=it["stem"] + ".%(ext)s",
                               force_video=True, frac=(i / n, 1 / n))
                job.items_done = i + 1
                continue
            target = outdir / f"{it['stem']}.{it['ext']}"
            self._http_download(job, it["url"], target, i, n)
            if s.get("save_caption") and it.get("caption"):
                key = f"{it.get('owner')}_{it.get('post')}" if it.get("post") else it["stem"]
                cap = outdir / f"{_sanitize(key, 120)}.txt"
                if not cap.exists():
                    write_caption(str(cap), _caption_text("", it.get("owner", ""), job.url, it.get("date", ""),
                                                         it["caption"], it.get("tags")))
            job.items_done = i + 1
            job.progress = min(0.999, (i + 1) / n)

    def _http_download(self, job: Job, url: str, target: Path, i: int, n: int):
        job.stage = "Medya indiriliyor" if n == 1 else f"Medya indiriliyor ({i + 1}/{n})"
        if target.exists() and target.stat().st_size > 0:
            job.files.append(str(target))
            return
        part = str(target) + ".part"
        job.parts.add(part)
        headers = {"User-Agent": tools.UA}
        ref = tools.referer_for(url)
        if ref:
            headers["Referer"] = ref
        req = urllib.request.Request(url, headers=headers)
        start = time.time()
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                job.check()
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                el = max(time.time() - start, 0.001)
                job.speed = got / el
                job.done_bytes, job.total_bytes = got, total
                if total:
                    job.eta = int((total - got) / job.speed) if job.speed else None
                    job.progress = min(0.999, (i + got / total) / n)
        os.replace(part, target)
        job.parts.discard(part)
        job.files.append(str(target))

    def _record(self, job: Job):
        size = 0
        for f in job.files:
            try:
                size += os.path.getsize(f)
            except OSError:
                pass
        job.size = size
        thumb_file = None
        if job.thumb:
            got = self.thumbs.get(job.thumb)
            if got:
                body, ctype = got
                ext = {"image/png": "png", "image/webp": "webp"}.get(ctype, "jpg")
                thumb_file = f"{job.id}.{ext}"
                try:
                    (config.thumbs_dir() / thumb_file).write_bytes(body)
                except OSError:
                    thumb_file = None
        self.history.add({
            "id": job.id, "title": job.title, "uploader": job.uploader, "url": job.url,
            "platform": job.platform, "kind_name": job.kind_name, "mode": job.mode, "label": job.label,
            "files": job.files, "size": size, "date": time.time(), "thumb_file": thumb_file,
        })

    # ---- motor güncellemesi --------------------------------------------- #
    @property
    def update_state(self) -> dict:
        return updater.state

    def update_engines(self):
        updater.run_update(tools.helper_cmd, tools.run_hidden, only_if_newer=True)
