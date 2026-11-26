"""Yakala için ağ gerektirmeyen testler.

Çalıştırma:  py -m pytest tests -q
Her test kendi geçici %APPDATA% / %LOCALAPPDATA% klasörünü kullanır; gerçek ayarlarına dokunmaz.
"""
from __future__ import annotations

import http.client
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from yakala import config
    importlib.reload(config)
    return tmp_path


def _engine(tmp_path):
    from yakala import config, engine, tools
    st = config.Settings()
    st.update({"download_dir": str(tmp_path / "dl"), "auto_update": False})
    return engine.Engine(st, config.History(), tools.ThumbCache()), st


# --------------------------------------------------------------------------- platform tanıma
@pytest.mark.parametrize("url,plat,kind", [
    ("https://youtu.be/abc", "youtube", "video"),
    ("https://www.youtube.com/shorts/abc", "youtube", "short"),
    ("https://www.youtube.com/playlist?list=PL1", "youtube", "playlist"),
    ("https://vxtwitter.com/a/status/1", "twitter", "post"),
    ("https://www.instagram.com/stories/natgeo/", "instagram", "story"),
    ("https://www.tiktok.com/@a/photo/1", "tiktok", "photo"),
    ("https://example.com/x", "other", "link"),
])
def test_platforms(url, plat, kind):
    from yakala import platforms
    u = platforms.normalize(url)
    assert platforms.detect(u) == plat
    assert platforms.kind(u) == kind


def test_mirror_normalized():
    from yakala import platforms
    assert platforms.normalize("https://fxtwitter.com/a/status/1").startswith("https://x.com/")


# --------------------------------------------------------------------------- boyut sınırı
def test_fit_format_picks_largest_that_fits():
    from yakala.engine import fit_format
    fmts = [
        {"format_id": "v1080", "vcodec": "avc1", "acodec": "none", "width": 1920, "height": 1080, "filesize": 40 << 20},
        {"format_id": "v480", "vcodec": "avc1", "acodec": "none", "width": 854, "height": 480, "filesize": 8 << 20},
        {"format_id": "v240", "vcodec": "avc1", "acodec": "none", "width": 426, "height": 240, "filesize": 3 << 20},
        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "filesize": 1 << 20},
    ]
    got = fit_format(fmts, 60, 10)
    assert got["spec"] == "v480+a" and got["size"] <= 10 << 20
    assert fit_format(fmts, 60, 1) is None


# --------------------------------------------------------------------------- iptal sınıfı
def test_cancelled_is_download_cancelled():
    import yt_dlp
    from yakala.engine import Cancelled
    assert issubclass(Cancelled, yt_dlp.utils.DownloadCancelled)


# --------------------------------------------------------------------------- kalıcı kuyruk
def test_queue_survives_restart(env):
    eng, _ = _engine(env)
    eng.settings.update({"concurrency": 1})
    from yakala.engine import Job
    j = Job("https://www.youtube.com/watch?v=jNQXAC9IVRw", "audio", {"audio_format": "mp3"}, {"title": "Deneme"})
    j.status = "paused"
    eng.jobs[j.id] = j
    eng._save_queue()
    eng2, _ = _engine(env)
    restored = [x for x in eng2.list() if x["title"] == "Deneme"]
    assert eng2.restored == 1 and restored and restored[0]["status"] == "paused"


# --------------------------------------------------------------------------- disk kontrolü
def test_disk_check(env, monkeypatch):
    import shutil
    from collections import namedtuple
    eng, _ = _engine(env)
    usage = namedtuple("u", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(1, 1, 10 << 20))
    with pytest.raises(ValueError, match="yer yok"):
        eng.submit({"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw", "mode": "video"})


# --------------------------------------------------------------------------- iptal duraklatmayı ezer
def test_cancel_clears_pause(env):
    eng, _ = _engine(env)
    from yakala.engine import Job
    j = Job("https://x.com/a/status/1", "video", {}, {})
    j.status = "running"
    eng.jobs[j.id] = j
    eng.action(j.id, "pause")
    eng.action(j.id, "cancel")
    assert j.cancel_flag and not j.pause_flag


# --------------------------------------------------------------------------- pano: dosya kopyalama
@pytest.mark.skipif(os.name != "nt", reason="Windows panosu")
def test_copy_files_roundtrip(tmp_path):
    from yakala import tools
    f = tmp_path / "örnek video.mp4"
    f.write_bytes(b"x")
    assert tools.copy_files([str(f)])
    assert tools.clipboard_files() == [str(f)]


def test_open_refuses_executables(tmp_path, monkeypatch):
    from yakala import tools
    f = tmp_path / "kotu.exe"
    f.write_bytes(b"MZ")
    opened = []
    monkeypatch.setattr(tools, "reveal_path", lambda p: opened.append(("reveal", p)) or True)
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(("start", p)), raising=False)
    tools.open_path(str(f))
    assert opened == [("reveal", str(f))]


# --------------------------------------------------------------------------- küçük resim önbelleği
def test_thumbcache_reverse_lookup():
    from yakala import tools
    c = tools.ThumbCache(limit=2)
    a = c.register("https://a/1.jpg")
    assert c.register("https://a/1.jpg") == a
    for i in range(10):
        c.register(f"https://b/{i}.jpg")
    assert c.url_of(a) is None and "https://a/1.jpg" not in c.by_url


# --------------------------------------------------------------------------- güncelleyici geri dönüşü
def test_broken_engine_falls_back(tmp_path):
    local = tmp_path / "local"
    eng = local / "Yakala" / "engines"
    bad = eng / "bozuk"
    (bad / "yt_dlp").mkdir(parents=True)
    (bad / "gallery_dl").mkdir(parents=True)
    (bad / "yt_dlp" / "__init__.py").write_text("raise ImportError('bozuk motor')")
    (eng / "active.txt").write_text("bozuk")
    code = ("import sys; sys.path.insert(0, r'%s'); from yakala import updater; "
            "print(updater.activate()); import yt_dlp; print('ok', yt_dlp.version.__version__)") % ROOT
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "LOCALAPPDATA": str(local)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[0] == "None" and "ok" in r.stdout
    assert not (eng / "active.txt").exists()


# --------------------------------------------------------------------------- telefondan erişim
class _FakeEngine:
    def __init__(self):
        self.sent = []

    def list(self):
        return []

    def submit(self, req):
        self.sent.append(req)
        return {"id": "x"}


@pytest.fixture()
def lan(env):
    from yakala import config, lanshare
    dl = env / "dl"
    dl.mkdir()
    media = dl / "video.mp4"
    media.write_bytes(bytes(range(256)) * 40)
    hist = config.History()
    hist.add({"id": "abc123", "title": "Deneme video", "platform": "youtube", "files": [str(media)], "date": time.time()})

    class App:
        settings = config.Settings()
        history = hist
        engine = _FakeEngine()

    App.settings.update({"lan_port": 18791, "lan_enabled": True, "lan_allow_send": True})
    share = lanshare.LanShare(App)
    assert share.start(), share.error
    yield share, App, media
    share.stop()


def _req(method, path, headers=None, body=None, port=18791):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r, data


def test_lan_requires_key(lan):
    r, _ = _req("GET", "/api/items")
    assert r.status == 401
    r, _ = _req("GET", "/")
    assert r.status == 401


def test_lan_key_sets_cookie_and_lists(lan):
    share, app, media = lan
    r, _ = _req("GET", f"/?k={share.key}")
    assert r.status == 303 and "HttpOnly" in r.getheader("Set-Cookie")
    cookie = r.getheader("Set-Cookie").split(";")[0]
    r, data = _req("GET", "/api/items", {"Cookie": cookie})
    items = json.loads(data)["data"]
    assert r.status == 200 and items[0]["title"] == "Deneme video"


def test_lan_range_request(lan):
    share, app, media = lan
    cookie = f"yakala_k={share.key}"
    r, data = _req("GET", "/f/abc123/0", {"Cookie": cookie, "Range": "bytes=10-19"})
    assert r.status == 206 and data == media.read_bytes()[10:20]
    assert r.getheader("Content-Range") == f"bytes 10-19/{media.stat().st_size}"
    r, data = _req("GET", "/f/abc123/0?dl=1", {"Cookie": cookie})
    assert r.status == 200 and "attachment" in r.getheader("Content-Disposition") and data == media.read_bytes()


def test_lan_no_arbitrary_files(lan):
    share, *_ = lan
    cookie = f"yakala_k={share.key}"
    for path in ("/f/abc123/5", "/f/zzz/0", "/f/abc123/../../etc", "/t/abc123"):
        r, _ = _req("GET", path, {"Cookie": cookie})
        assert r.status == 404, path


def test_lan_send_needs_header(lan):
    share, app, _ = lan
    cookie = f"yakala_k={share.key}"
    body = json.dumps({"text": "bak https://youtu.be/abc", "mode": "audio"})
    r, _ = _req("POST", "/api/send", {"Cookie": cookie, "Content-Type": "application/json"}, body)
    assert r.status == 400 and not app.engine.sent
    r, data = _req("POST", "/api/send", {"Cookie": cookie, "Content-Type": "application/json", "X-Yakala": "1"}, body)
    assert r.status == 200 and app.engine.sent[0]["mode"] == "audio"


def test_lan_blocks_brute_force(lan):
    for _ in range(25):
        _req("GET", "/api/items", {"Cookie": "yakala_k=yanlis"})
    r, _ = _req("GET", "/api/items", {"Cookie": "yakala_k=yanlis"})
    assert r.status == 429


def test_lan_rotate_revokes(lan):
    share, *_ = lan
    old = share.key
    share.rotate_key()
    r, _ = _req("GET", "/api/items", {"Cookie": f"yakala_k={old}"})
    assert r.status == 401
