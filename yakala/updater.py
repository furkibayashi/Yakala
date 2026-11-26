"""İndirme motorlarını (yt-dlp, gallery-dl) uygulamayı yeniden derlemeden güncel tutar.

PyPI'dan saf Python wheel'leri indirilir, SHA-256 ile doğrulanır ve
%LOCALAPPDATA%\\Yakala\\engines\\<sürüm>\\ altına açılır. Açılışta (yt_dlp içe
aktarılmadan önce) etkin klasör sys.path'in başına eklenir; böylece hem kaynak
koddan hem de PyInstaller ile paketlenmiş exe'den çalışırken yeni sürüm kullanılır.
Yeni sürüm bir alt süreçte denenir; çalışmazsa etkinleştirilmez ve paketle gelen
sürüm kullanılmaya devam eder.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

UA = "Yakala-updater"
PACKAGES = ("yt-dlp", "gallery-dl")
CHECK_INTERVAL = 20 * 3600

state = {"running": False, "message": "", "ok": None, "pending": False, "latest": {}, "checked": 0}
_lock = threading.Lock()


def engines_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "Yakala" / "engines"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _active_file() -> Path:
    return engines_dir() / "active.txt"


def active_dir() -> Path | None:
    try:
        name = _active_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    d = engines_dir() / name
    return d if name and (d / "yt_dlp").is_dir() and (d / "gallery_dl").is_dir() else None


_loaded = {"dir": None}


def activate() -> str | None:
    """yt_dlp/gallery_dl içe aktarılmadan önce çağrılmalı. Güncel motor açılamazsa paketle gelene döner."""
    if "yt_dlp" in sys.modules or "gallery_dl" in sys.modules:
        return None
    d = active_dir()
    if not d or str(d) in sys.path:
        return None
    sys.path.insert(0, str(d))
    try:
        import gallery_dl  # noqa: F401
        import yt_dlp  # noqa: F401
    except Exception:  # noqa: BLE001
        sys.path.remove(str(d))
        for name in [m for m in sys.modules if m.split(".")[0] in ("yt_dlp", "yt_dlp_ejs", "gallery_dl")]:
            del sys.modules[name]
        try:
            _active_file().unlink()
        except OSError:
            pass
        return None
    _loaded["dir"] = d
    return str(d)


def _vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def current_versions() -> dict:
    out = {}
    try:
        import yt_dlp.version as yv
        out["yt-dlp"] = yv.__version__
    except Exception:  # noqa: BLE001
        out["yt-dlp"] = "?"
    try:
        import gallery_dl.version as gv
        out["gallery-dl"] = gv.__version__
    except Exception:  # noqa: BLE001
        out["gallery-dl"] = "?"
    return out


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _wheel(pkg: str, version: str | None = None) -> tuple[str, str, str]:
    """(sürüm, wheel url, sha256)"""
    data = _get_json(f"https://pypi.org/pypi/{pkg}/{version}/json" if version else f"https://pypi.org/pypi/{pkg}/json")
    ver = data["info"]["version"]
    for f in data.get("urls") or []:
        if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("-py3-none-any.whl"):
            return ver, f["url"], f["digests"]["sha256"]
    raise RuntimeError(f"{pkg} {ver} için uygun paket bulunamadı.")


def latest_versions() -> dict:
    return {p: _get_json(f"https://pypi.org/pypi/{p}/json")["info"]["version"] for p in PACKAGES}


def _download(url: str, sha256: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
    if hashlib.sha256(body).hexdigest() != sha256:
        raise RuntimeError("İndirilen paket doğrulanamadı (SHA-256 uyuşmuyor).")
    return body


def _requires(wheel: zipfile.ZipFile) -> list[str]:
    meta = next((n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")), None)
    if not meta:
        return []
    text = wheel.read(meta).decode("utf-8", "replace")
    return [ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("Requires-Dist:")]


def updates_available() -> dict:
    """Paket adı -> (şimdiki, en yeni) ; yalnızca yenisi olanlar."""
    cur = current_versions()
    pending = _pending_versions()
    latest = latest_versions()
    state["latest"] = latest
    state["checked"] = time.time()
    out = {}
    for p, v in latest.items():
        have = max(_vtuple(cur.get(p, "0")), _vtuple(pending.get(p, "0")))
        if _vtuple(v) > have:
            out[p] = (cur.get(p, "?"), v)
    return out


def _pending_versions() -> dict:
    d = active_dir()
    if not d:
        return {}
    try:
        return json.loads((d / "versions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def install(helper_cmd, run_hidden) -> dict:
    """En yeni motorları indirip dener ve etkinleştirir. Sürüm sözlüğü döner."""
    ytv, yt_url, yt_sha = _wheel("yt-dlp")
    gdv, gd_url, gd_sha = _wheel("gallery-dl")
    target = engines_dir() / f"yt-dlp-{ytv}_gallery-dl-{gdv}"
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        yt = zipfile.ZipFile(io.BytesIO(_download(yt_url, yt_sha)))
        yt.extractall(tmp)
        for req in _requires(yt):
            m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)
            if m:
                _, ej_url, ej_sha = _wheel("yt-dlp-ejs", m.group(1))
                zipfile.ZipFile(io.BytesIO(_download(ej_url, ej_sha))).extractall(tmp)
                break
        zipfile.ZipFile(io.BytesIO(_download(gd_url, gd_sha))).extractall(tmp)
        versions = {"yt-dlp": ytv, "gallery-dl": gdv}
        (tmp / "versions.json").write_text(json.dumps(versions), encoding="utf-8")
        r = run_hidden(helper_cmd("--engine-test", str(tmp)), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
        if r.returncode != 0 or f"yt-dlp {ytv}" not in (r.stdout or ""):
            tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["bilinmeyen hata"])[-1]
            raise RuntimeError(f"Yeni motor denenirken hata oluştu: {tail}")
        shutil.rmtree(target, ignore_errors=True)
        os.replace(tmp, target)
        prev = active_dir()
        _active_file().write_text(target.name, encoding="utf-8")
        keep = {target, prev, _loaded["dir"]}   # çalışan süreç yüklediği motoru kullanmaya devam ediyor
        for old in engines_dir().iterdir():
            if old.is_dir() and old not in keep and not old.name.endswith(".tmp"):
                shutil.rmtree(old, ignore_errors=True)
        return versions
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def engine_test(path: str) -> int:
    """Alt süreç: verilen klasördeki motorları içe aktarıp kısa bir deneme yapar."""
    sys.path.insert(0, path)
    import gallery_dl.version as gv
    import yt_dlp
    import yt_dlp.version as yv

    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        assert ydl.get_info_extractor("Youtube") is not None
    from gallery_dl import extractor
    assert extractor.find("https://www.instagram.com/p/abc/") is not None
    print(f"yt-dlp {yv.__version__}")
    print(f"gallery-dl {gv.__version__}")
    return 0


def run_update(helper_cmd, run_hidden, *, only_if_newer: bool = True):
    """Arka planda çalışır; durum `state` sözlüğünde tutulur."""
    with _lock:
        if state["running"]:
            return
        state.update(running=True, ok=None, message="Güncellemeler denetleniyor…")

    def work():
        try:
            if only_if_newer:
                newer = updates_available()
                if not newer:
                    state.update(ok=True, message="Motorlar güncel.")
                    return
            state["message"] = "Yeni motorlar indiriliyor…"
            versions = install(helper_cmd, run_hidden)
            cur = current_versions()
            if all(_vtuple(cur.get(k)) >= _vtuple(v) for k, v in versions.items()):
                state.update(ok=True, message="Motorlar güncel.")
            else:
                state.update(ok=True, pending=True,
                             message=f"yt-dlp {versions['yt-dlp']} ve gallery-dl {versions['gallery-dl']} hazır. "
                                     "Etkinleşmesi için uygulamayı yeniden başlat.")
        except Exception as e:  # noqa: BLE001
            state.update(ok=False, message=f"Güncellenemedi: {e}")
        finally:
            state["running"] = False

    threading.Thread(target=work, daemon=True).start()


def maybe_auto(helper_cmd, run_hidden):
    """Son denetimden bu yana yeterince zaman geçtiyse arka planda güncelle."""
    stamp = engines_dir() / "last_check.txt"
    try:
        last = float(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = 0
    if time.time() - last < CHECK_INTERVAL:
        return
    try:
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    run_update(helper_cmd, run_hidden, only_if_newer=True)
