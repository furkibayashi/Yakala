"""Yardımcılar: ffmpeg/deno bulma, pano, klasör seçici, dosya açma, hata çevirisi."""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from collections import OrderedDict
from pathlib import Path

from . import config

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------- #
# Alt süreç komutları (kaynak koddan ya da paketlenmiş exe'den çalışabilsin)
# --------------------------------------------------------------------------- #
def helper_cmd(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        console = exe[:-5] + ".exe"
        if os.path.exists(console):
            exe = console
    root = str(Path(__file__).resolve().parent.parent)
    return [exe, "-c", f"import sys; sys.path.insert(0, {root!r}); from yakala.__main__ import main; main()", *args]


def run_hidden(cmd, **kw):
    return subprocess.run(cmd, creationflags=NO_WINDOW, **kw)


# --------------------------------------------------------------------------- #
# ffmpeg ve deno
# --------------------------------------------------------------------------- #
_ff_lock = threading.Lock()
FFMPEG_ZIP = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
ffmpeg_install = {"running": False, "progress": 0.0, "error": "", "done": False}


def ffmpeg_info() -> dict:
    """{dir, ffmpeg, ffprobe, source} — ffmpeg yoksa dir None olur."""
    with _ff_lock:
        bd = config.bin_dir()
        ff, fp = bd / "ffmpeg.exe", bd / "ffprobe.exe"
        if ff.exists() and fp.exists():
            return {"dir": str(bd), "ffmpeg": True, "ffprobe": True, "source": "full"}
        sys_ff, sys_fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if sys_ff and sys_fp:
            return {"dir": str(Path(sys_ff).parent), "ffmpeg": True, "ffprobe": True, "source": "system"}
        if not ff.exists():
            try:
                import imageio_ffmpeg  # type: ignore

                src = imageio_ffmpeg.get_ffmpeg_exe()
                shutil.copy2(src, ff)
            except Exception:
                pass
        if ff.exists():
            return {"dir": str(bd), "ffmpeg": True, "ffprobe": fp.exists(), "source": "bundled"}
        if sys_ff:
            return {"dir": str(Path(sys_ff).parent), "ffmpeg": True, "ffprobe": False, "source": "system"}
        return {"dir": None, "ffmpeg": False, "ffprobe": False, "source": "none"}


def install_full_ffmpeg():
    """yt-dlp'nin resmi FFmpeg derlemesini indirip bin klasörüne açar (ffprobe dahil)."""
    if ffmpeg_install["running"]:
        return
    ffmpeg_install.update(running=True, progress=0.0, error="", done=False)

    def work():
        tmp = config.bin_dir() / "ffmpeg-download.zip"
        try:
            req = urllib.request.Request(FFMPEG_ZIP, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        ffmpeg_install["progress"] = got / total * 0.95
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():
                    base = name.rsplit("/", 1)[-1].lower()
                    if base in ("ffmpeg.exe", "ffprobe.exe"):
                        target = config.bin_dir() / base
                        with z.open(name) as src, open(str(target) + ".new", "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.replace(str(target) + ".new", target)
            ffmpeg_install.update(progress=1.0, done=True)
        except Exception as e:  # noqa: BLE001
            ffmpeg_install["error"] = f"FFmpeg indirilemedi: {e}"
        finally:
            ffmpeg_install["running"] = False
            try:
                tmp.unlink()
            except OSError:
                pass

    threading.Thread(target=work, daemon=True).start()


def deno_path() -> str | None:
    if getattr(sys, "frozen", False):
        p = Path(getattr(sys, "_MEIPASS", "")) / "bin" / "deno.exe"
        if p.exists():
            return str(p)
    try:
        import deno  # type: ignore

        p = deno.find_deno_bin()
        if p and os.path.exists(p):
            return str(p)
    except Exception:
        pass
    return shutil.which("deno")


# --------------------------------------------------------------------------- #
# Pano (Windows)
# --------------------------------------------------------------------------- #
def clipboard_text() -> str:
    if os.name != "nt":
        return ""
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return ""
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        threading.Event().wait(0.03)
    else:
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)[:20000]
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


# --------------------------------------------------------------------------- #
# Klasör seçici ve dosya gezgini
# --------------------------------------------------------------------------- #
def pick_folder(initial: str = "") -> str:
    try:
        r = run_hidden(helper_cmd("--pick-folder", initial or ""), capture_output=True, text=True,
                       encoding="utf-8", timeout=600)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def pick_file(initial: str = "") -> str:
    try:
        r = run_hidden(helper_cmd("--pick-file", initial or ""), capture_output=True, text=True,
                       encoding="utf-8", timeout=600)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def open_path(path: str) -> bool:
    if path and os.path.exists(path):
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    return False


def reveal_path(path: str) -> bool:
    if path and os.path.isfile(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        return True
    if path and os.path.isdir(path):
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    parent = os.path.dirname(path or "")
    if parent and os.path.isdir(parent):
        os.startfile(parent)  # type: ignore[attr-defined]
        return True
    return False


# --------------------------------------------------------------------------- #
# Küçük resim vekili (Instagram/TikTok görselleri başka sitelerde açılmıyor)
# --------------------------------------------------------------------------- #
class ThumbCache:
    def __init__(self, limit: int = 400):
        self.urls: OrderedDict[str, str] = OrderedDict()
        self.data: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.limit = limit
        self.lock = threading.Lock()
        self._n = 0

    def register(self, url: str | None) -> str | None:
        if not url or not re.match(r"^https?://", url):
            return None
        with self.lock:
            for tok, u in self.urls.items():
                if u == url:
                    return tok
            self._n += 1
            tok = f"t{self._n:x}{os.urandom(3).hex()}"
            self.urls[tok] = url
            while len(self.urls) > self.limit * 3:
                self.urls.popitem(last=False)
            return tok

    def url_of(self, tok: str) -> str | None:
        with self.lock:
            return self.urls.get(tok)

    def get(self, tok: str) -> tuple[bytes, str] | None:
        with self.lock:
            if tok in self.data:
                self.data.move_to_end(tok)
                return self.data[tok]
            url = self.urls.get(tok)
        if not url:
            return None
        try:
            body, ctype = fetch_bytes(url, limit=12 << 20)
        except Exception:
            return None
        with self.lock:
            self.data[tok] = (body, ctype)
            while len(self.data) > self.limit:
                self.data.popitem(last=False)
        return body, ctype


def referer_for(url: str) -> str | None:
    host = (re.match(r"https?://([^/]+)", url) or [None, ""])[1].lower()
    if "cdninstagram" in host or "fbcdn" in host:
        return "https://www.instagram.com/"
    if "tiktok" in host:
        return "https://www.tiktok.com/"
    if "twimg" in host:
        return "https://x.com/"
    return None


def fetch_bytes(url: str, limit: int = 12 << 20) -> tuple[bytes, str]:
    headers = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    ref = referer_for(url)
    if ref:
        headers["Referer"] = ref
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read(limit + 1)
        if len(body) > limit:
            raise ValueError("çok büyük")
        return body, r.headers.get_content_type() or "image/jpeg"


# --------------------------------------------------------------------------- #
# Hata mesajlarını anlaşılır Türkçeye çevir
# --------------------------------------------------------------------------- #
LOGIN_HINT = "Ayarlar → Hesap çerezleri bölümünden giriş yaptığın tarayıcıyı seç."

_ERRORS = [
    (r"confirm you.?re not a bot|sign in to confirm", "YouTube bot doğrulaması istiyor. " + LOGIN_HINT),
    (r"confirm your age|age.?restricted|inappropriate for some users", "Bu içerik yaş doğrulaması istiyor. " + LOGIN_HINT),
    (r"private video|this video is private", "Bu video gizli; yalnızca sahibi ve izin verdikleri görebilir."),
    (r"members.only|join this channel", "Bu video yalnızca kanal üyelerine açık."),
    (r"premiere|live event will begin|is upcoming", "Bu yayın henüz başlamadı."),
    (r"failed to decrypt with dpapi|could not copy .*cookie database|app.bound",
     "Chrome/Edge çerezleri okunamadı. Tarayıcıyı tamamen kapatıp tekrar dene ya da Firefox / cookies.txt kullan."),
    (r"could not find .* cookies database|cookies? .*not found|unsupported browser",
     "Seçtiğin tarayıcıda çerez bulunamadı. Ayarlardan başka bir tarayıcı seç."),
    (r"not available in your country|geo.?restrict|blocked it in your country", "Bu içerik bulunduğun ülkede engelli."),
    (r"login required|log in|login_required|requires? (an )?(account|authentication)|you need to log|redirect to login|"
     r"not logged in|authorization|unauthorized|restricted|empty media response|inaccessible|"
     r"main webpage is locked behind the login page",
     "Bu içerik için giriş gerekiyor (hikâyeler, gizli hesaplar ve bazı gönderiler). " + LOGIN_HINT),
    (r"429|too many requests|rate.?limit", "Platform çok fazla istek algıladı. Birkaç dakika bekleyip tekrar dene ya da çerez ekle."),
    (r"video unavailable|unavailable|has been removed|no longer available|does not exist|404|page not found|status is unavailable|deleted",
     "İçerik bulunamadı; silinmiş, gizlenmiş ya da bağlantı hatalı olabilir."),
    (r"unsupported url", "Bu bağlantı desteklenmiyor. Bir video, gönderi, hikâye ya da liste bağlantısı yapıştır."),
    (r"getaddrinfo|name or service|timed out|connection (refused|reset|aborted)|network is unreachable|"
     r"unable to download (webpage|json)|urlopen error|ssl",
     "İnternete ya da siteye bağlanılamadı. Bağlantını kontrol edip tekrar dene."),
    (r"ffmpeg|ffprobe", "FFmpeg gerekli. Ayarlar → Sistem bölümünden FFmpeg'i kur."),
    (r"no space left|disk full", "Diskte yer kalmadı."),
    (r"permission denied|access is denied", "Klasöre yazma izni yok. Ayarlardan başka bir indirme klasörü seç."),
    (r"no video (could be found|formats)|there.?s no video|no video in this", "Bu gönderide video yok."),
    (r"requested format is not available", "İstenen kalite bu içerikte yok. Daha düşük bir kalite seç."),
    (r"drm", "Bu içerik DRM korumalı; indirilemez."),
]


def friendly_error(msg: str) -> str:
    raw = str(msg or "").strip()
    low = raw.lower()
    for pat, text in _ERRORS:
        if re.search(pat, low):
            return text
    clean = re.sub(r"^(ERROR:\s*)+", "", raw)
    clean = re.sub(r"^\[[^\]]+\]\s*([\w-]+:\s*)?", "", clean)
    clean = clean.split("; please report this issue")[0]
    return (clean[:240] or "Bilinmeyen bir hata oluştu.")
