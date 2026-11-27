"""Uygulama güncellemesi: GitHub'da yeni bir sürüm yayınlanınca Yakala kendini günceller.

Akış:
1. GitHub'daki son sürüm (releases/latest) okunur; etiket (v1.4.0) mevcut sürümden yeniyse
   "-windows.zip" dosyası bulunur.
2. Zip indirilir, SHA-256 ile doğrulanır (GitHub'ın verdiği özet ya da sürüm notundaki
   "SHA-256: `...`" satırı) ve %LOCALAPPDATA%\\Yakala\\update altına açılır.
3. Kurulum için küçük bir betik başlatılır: Yakala kapanınca yeni dosyaları kurulum
   klasörüne kopyalar ve istenirse Yakala'yı yeniden açar. Ayarlar ve geçmiş %APPDATA%'da
   durduğu için etkilenmez.

Yalnızca paketlenmiş exe'de kurulum yapılır; kaynak koddan çalışırken yalnızca haber verilir.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import config

REPO = "furkibayashi/Yakala"
CHECK_EVERY = 6 * 3600
NO_WINDOW = 0x08000000
DETACHED = 0x00000008

state: dict = {
    "checking": False, "checked": 0, "error": "",
    "available": None,          # {version, notes, url, size}
    "downloading": False, "progress": 0.0,
    "ready": False,             # indirildi, kurulmayı bekliyor
}
_lock = threading.Lock()
_asset: dict = {}


def api_url() -> str:
    # Testler için yerel bir sahte sürüm sunucusuna yönlendirilebilir.
    return os.environ.get("YAKALA_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:4])


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_install() -> tuple[bool, str]:
    if not frozen():
        return False, "Kaynak koddan çalışıyorsun; güncellemek için depodan son sürümü çek."
    d = install_dir()
    try:
        probe = d / ".yakala-yazma-denemesi"
        probe.write_text("x")
        probe.unlink()
    except OSError:
        return False, f"{d} klasörüne yazılamıyor. Yakala'yı yazılabilir bir klasöre taşı ya da zip'i elle çıkar."
    return True, ""


def update_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "Yakala" / "update"
    p.mkdir(parents=True, exist_ok=True)
    return p


def public() -> dict:
    ok, why = can_install()
    return {**{k: v for k, v in state.items()}, "current": config.APP_VERSION, "can_install": ok,
            "cannot_reason": why}


# ---------------------------------------------------------------------- denetim
def check() -> dict | None:
    with _lock:
        if state["checking"]:
            return state["available"]
        state.update(checking=True, error="")
    try:
        req = urllib.request.Request(api_url(), headers={"User-Agent": "Yakala-guncelleyici",
                                                         "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        version = str(data.get("tag_name") or "").lstrip("vV")
        state["checked"] = time.time()
        if not version or _vt(version) <= _vt(config.APP_VERSION) or data.get("draft") or data.get("prerelease"):
            state["available"] = None
            return None
        asset = next((a for a in data.get("assets") or [] if str(a.get("name", "")).endswith("-windows.zip")), None)
        if not asset:
            state["available"] = None
            return None
        body = str(data.get("body") or "")
        sha = str(asset.get("digest") or "").removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            m = re.search(r"SHA-?256:?\s*`?([0-9a-fA-F]{64})", body)
            sha = m.group(1).lower() if m else ""
        _asset.update(url=asset.get("browser_download_url"), sha=sha, size=asset.get("size") or 0, version=version)
        prev = state.get("available") or {}
        state["available"] = {"version": version, "notes": body[:4000], "url": data.get("html_url") or "",
                              "size": asset.get("size") or 0, "published": data.get("published_at") or ""}
        if prev.get("version") != version:
            state["ready"] = _ready_dir(version) is not None
        return state["available"]
    except Exception as e:  # noqa: BLE001
        state["error"] = f"Güncelleme denetlenemedi: {e}"
        return None
    finally:
        state["checking"] = False


# ---------------------------------------------------------------------- indirme
def _ready_dir(version: str) -> Path | None:
    d = update_root() / version
    exe = next(d.glob("**/Yakala.exe"), None) if d.is_dir() else None
    return exe.parent if exe and (d / ".tamam").exists() else None


def download() -> bool:
    if not _asset.get("url"):
        check()
    if not _asset.get("url"):
        state["error"] = state["error"] or "İndirilecek yeni sürüm yok."
        return False
    if not _asset.get("sha"):
        state["error"] = "Yeni sürümün doğrulama özeti (SHA-256) bulunamadı; güvenlik için indirilmedi."
        return False
    version = _asset["version"]
    if _ready_dir(version):
        state["ready"] = True
        return True
    with _lock:
        if state["downloading"]:
            return False
        state.update(downloading=True, progress=0.0, error="")
    root = update_root()
    tmp_zip = root / f"{version}.zip.part"
    try:
        req = urllib.request.Request(_asset["url"], headers={"User-Agent": "Yakala-guncelleyici"})
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp_zip, "wb") as f:
            total = int(r.headers.get("Content-Length") or _asset.get("size") or 0)
            got = 0
            while True:
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if total:
                    state["progress"] = min(0.97, got / total * 0.97)
        if h.hexdigest() != _asset["sha"]:
            raise RuntimeError("İndirilen dosya doğrulanamadı (SHA-256 uyuşmuyor); güncelleme iptal edildi.")
        target = root / version
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        with zipfile.ZipFile(tmp_zip) as z:
            base = target.resolve()
            for member in z.infolist():
                dest = (target / member.filename).resolve()
                if base != dest and base not in dest.parents:
                    raise RuntimeError("Güncelleme paketinde geçersiz dosya yolu var.")
            z.extractall(target)
        if not next(target.glob("**/Yakala.exe"), None):
            raise RuntimeError("Güncelleme paketinde Yakala.exe bulunamadı.")
        (target / ".tamam").write_text(version)
        for old in root.iterdir():          # eski indirmeleri temizle
            if old.name not in (version, ) and old != tmp_zip:
                (shutil.rmtree if old.is_dir() else Path.unlink)(old)
        state.update(ready=True, progress=1.0)
        return True
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e) if isinstance(e, RuntimeError) else f"Güncelleme indirilemedi: {e}"
        return False
    finally:
        state["downloading"] = False
        try:
            tmp_zip.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------- kurulum
_SCRIPT = r"""@echo off
chcp 65001 >nul
set "PID={pid}"
set "SRC={src}"
set "DST={dst}"
:bekle
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul && (ping -n 2 127.0.0.1 >nul & goto bekle)
ping -n 2 127.0.0.1 >nul
robocopy "%SRC%" "%DST%" /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 (echo %DATE% %TIME% robocopy hata %ERRORLEVEL%>>"%DST%\guncelleme-hatasi.txt")
{restart}
rd /s /q "{root}" 2>nul
(goto) 2>nul & del "%~f0"
"""


def install(restart: bool) -> bool:
    """Kurulum betiğini başlatır. Ardından uygulama kapanmalıdır."""
    ok, why = can_install()
    if not ok:
        state["error"] = why
        return False
    version = (state.get("available") or {}).get("version") or _asset.get("version") or ""
    src = _ready_dir(version) if version else None
    if not src:
        state["error"] = "Önce güncellemeyi indir."
        return False
    dst = install_dir()
    script = Path(tempfile.gettempdir()) / f"yakala-guncelle-{os.getpid()}.cmd"
    script.write_text(_SCRIPT.format(
        pid=os.getpid(), src=src, dst=dst, root=update_root() / version,
        restart=f'start "" "{dst / "Yakala.exe"}"' if restart else "rem yeniden başlatma yok",
    ), encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=NO_WINDOW | DETACHED,
                     close_fds=True, cwd=tempfile.gettempdir())
    state["installing"] = True
    return True


def on_exit(settings):
    """Uygulama kapanırken: otomatik güncelleme açık ve indirilmiş sürüm varsa kur (yeniden açmadan)."""
    if state.get("installing") or not state.get("ready"):
        return
    if settings.get("app_auto_update"):
        install(restart=False)


# ---------------------------------------------------------------------- arka plan
def cleanup_stale():
    """Kurulmuş ya da eski sürümlere ait indirilmiş paketleri sil."""
    try:
        for d in update_root().iterdir():
            if d.is_dir() and _vt(d.name) <= _vt(config.APP_VERSION):
                shutil.rmtree(d, ignore_errors=True)
            elif d.suffix == ".part":
                d.unlink()
    except OSError:
        pass


def start_background(settings):
    def loop():
        cleanup_stale()
        time.sleep(8)
        while True:
            if settings.get("app_auto_update"):
                if check() and can_install()[0] and not state["ready"]:
                    download()
            time.sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True).start()
