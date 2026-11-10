"""Ayarlar, geçmiş ve uygulama klasörleri."""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Yakala"
APP_VERSION = "1.0.0"


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def bin_dir() -> Path:
    p = app_dir() / "bin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def thumbs_dir() -> Path:
    p = app_dir() / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_dir() -> Path:
    """Paketlenmiş (PyInstaller) ya da kaynak koddan çalışırken web dosyalarının kökü."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "yakala"
    return Path(__file__).resolve().parent


def default_download_dir() -> str:
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        downloads = Path.home()
    return str(downloads / APP_NAME)


DEFAULTS: dict = {
    "download_dir": default_download_dir(),
    "platform_folders": True,
    "filename": "title_id",
    "concurrency": 2,
    "video_quality": "best",
    "video_container": "mp4",
    "compat_codecs": True,
    "audio_format": "mp3",
    "audio_quality": "320",
    "embed_thumbnail": True,
    "embed_metadata": True,
    "subtitles": False,
    "sub_langs": "tr,en",
    "cookies_mode": "none",
    "cookies_browser": "firefox",
    "cookies_file": "",
    "theme": "dark",
    "clipboard_watch": True,
    "sound": True,
    "rate_limit": "",
    "proxy": "",
}

FILENAME_TEMPLATES = {
    "title": "%(title).120B.%(ext)s",
    "title_id": "%(title).100B [%(id)s].%(ext)s",
    "uploader_title": "%(uploader,channel,creator|Bilinmeyen).40B - %(title).100B.%(ext)s",
    "date_title": "%(upload_date>%Y-%m-%d|0000-00-00)s - %(title).100B.%(ext)s",
}

CHOICES = {
    "filename": set(FILENAME_TEMPLATES),
    "video_quality": {"best", "2160", "1440", "1080", "720", "480", "360"},
    "video_container": {"mp4", "mkv"},
    "audio_format": {"mp3", "m4a", "opus", "flac", "wav"},
    "audio_quality": {"best", "320", "256", "192", "128"},
    "cookies_mode": {"none", "browser", "file"},
    "cookies_browser": {"firefox", "chrome", "edge", "brave", "opera", "vivaldi", "chromium"},
    "theme": {"dark", "light"},
}


class JsonStore:
    def __init__(self, path: Path, default):
        self.path = path
        self.lock = threading.RLock()
        self.data = copy.deepcopy(default)
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(default, dict) and isinstance(loaded, dict):
                self.data.update(loaded)
            elif isinstance(default, list) and isinstance(loaded, list):
                self.data = loaded
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)


class Settings(JsonStore):
    def __init__(self):
        super().__init__(app_dir() / "settings.json", DEFAULTS)
        self._sanitize()

    def _sanitize(self):
        d = self.data
        for k, allowed in CHOICES.items():
            if str(d.get(k)) not in allowed:
                d[k] = DEFAULTS[k]
        try:
            d["concurrency"] = max(1, min(6, int(d.get("concurrency", 2))))
        except (TypeError, ValueError):
            d["concurrency"] = 2
        for k, v in DEFAULTS.items():
            if isinstance(v, bool):
                d[k] = bool(d.get(k, v))

    def get(self, key):
        with self.lock:
            return self.data.get(key, DEFAULTS.get(key))

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data)

    def update(self, changes: dict) -> dict:
        with self.lock:
            for k, v in (changes or {}).items():
                if k in DEFAULTS:
                    self.data[k] = v
            self._sanitize()
            self.save()
            return copy.deepcopy(self.data)


class History(JsonStore):
    LIMIT = 1000

    def __init__(self):
        super().__init__(app_dir() / "history.json", [])

    def add(self, entry: dict):
        with self.lock:
            entry.setdefault("date", time.time())
            self.data.insert(0, entry)
            for old in self.data[self.LIMIT:]:
                _remove_thumb(old)
            del self.data[self.LIMIT:]
            self.save()

    def items(self) -> list:
        with self.lock:
            return copy.deepcopy(self.data)

    def remove(self, entry_id: str):
        with self.lock:
            for e in [e for e in self.data if e.get("id") == entry_id]:
                _remove_thumb(e)
            self.data = [e for e in self.data if e.get("id") != entry_id]
            self.save()

    def clear(self):
        with self.lock:
            for e in self.data:
                _remove_thumb(e)
            self.data = []
            self.save()


def _remove_thumb(entry: dict):
    name = entry.get("thumb_file")
    if name:
        try:
            (thumbs_dir() / name).unlink()
        except OSError:
            pass
