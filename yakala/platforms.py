"""Bağlantı tanıma: hangi platform, hangi içerik türü."""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)

_HOSTS = {
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "twitter": ("twitter.com", "x.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com", "twittpr.com"),
    "tiktok": ("tiktok.com",),
    "instagram": ("instagram.com", "instagr.am", "ddinstagram.com"),
}

_TWITTER_MIRRORS = {"fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com", "twittpr.com"}

NAMES = {
    "youtube": "YouTube",
    "twitter": "X",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "other": "Diğer site",
}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def detect(url: str) -> str:
    host = _host(url)
    for key, domains in _HOSTS.items():
        if any(_host_matches(host, d) for d in domains):
            return key
    return "other"


def normalize(url: str) -> str:
    url = url.strip().strip("<>").rstrip(").,;!?'\"]")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    base = host[4:] if host.startswith("www.") else host
    if base in _TWITTER_MIRRORS or any(base.endswith("." + m) for m in _TWITTER_MIRRORS):
        parts = parts._replace(netloc="x.com")
    elif base == "ddinstagram.com":
        parts = parts._replace(netloc="www.instagram.com")
    elif base in ("m.youtube.com", "music.youtube.com"):
        parts = parts._replace(netloc="www.youtube.com")
    return urlunparse(parts)


def kind(url: str) -> str:
    """Bağlantının neyi gösterdiğine dair kaba bir tahmin (arayüzdeki etiket için)."""
    platform = detect(url)
    try:
        p = urlparse(url)
    except ValueError:
        return "link"
    path = p.path.lower()
    query = p.query.lower()
    if platform == "youtube":
        if "/shorts/" in path:
            return "short"
        if "list=" in query and "v=" not in query:
            return "playlist"
        if path.startswith("/@") or path.startswith("/channel/") or path.startswith("/c/"):
            return "channel"
        return "video"
    if platform == "instagram":
        if "/stories/highlights/" in path or "/s/" in path:
            return "highlight"
        if "/stories/" in path:
            return "story"
        if "/reel/" in path or "/reels/" in path:
            return "reel"
        if "/p/" in path or "/tv/" in path:
            return "post"
        return "profile"
    if platform == "tiktok":
        if "/photo/" in path:
            return "photo"
        if "/video/" in path or _host(url).startswith(("vm.", "vt.")) or "/t/" in path:
            return "video"
        return "profile"
    if platform == "twitter":
        if "/status/" in path:
            return "post"
        return "profile"
    return "link"


KIND_NAMES = {
    "video": "Video",
    "short": "Shorts",
    "playlist": "Oynatma listesi",
    "channel": "Kanal",
    "story": "Hikâye",
    "highlight": "Öne çıkan",
    "reel": "Reels",
    "post": "Gönderi",
    "profile": "Profil",
    "photo": "Fotoğraf",
    "link": "Bağlantı",
}


def extract_urls(text: str) -> list[str]:
    seen, out = set(), []
    for m in URL_RE.finditer(text or ""):
        u = normalize(m.group(0))
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def describe(url: str) -> dict:
    plat = detect(url)
    k = kind(url)
    return {
        "url": url,
        "platform": plat,
        "platform_name": NAMES[plat],
        "kind": k,
        "kind_name": KIND_NAMES.get(k, "Bağlantı"),
    }
