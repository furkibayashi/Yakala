"""Yeni Yakala sürümünü derleyip GitHub'da yayınlar.

Kullanıcılardaki Yakala, yayınlanan sürümü kendiliğinden bulup kurar. Bunun için sürümün
"Yakala-<sürüm>-windows.zip" dosyasını ve "SHA-256: `...`" satırını taşıması gerekir;
bu betik ikisini de doğru hazırlar.

Kullanım:
    1. yakala/config.py içinde APP_VERSION'ı yükselt (ör. "1.5.0").
    2. Değişiklikleri commit'le ve GitHub'a gönder (git push).
    3. Sürüm notlarını bir dosyaya yaz (ör. notlar.md).
    4. py yayinla.py notlar.md

Gereksinimler: gh (GitHub CLI) ile giriş yapılmış olmalı; pip install -r requirements.txt pyinstaller
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("›", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def version() -> str:
    text = (ROOT / "yakala" / "config.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([\d.]+)"', text)
    if not m:
        sys.exit("yakala/config.py içinde APP_VERSION bulunamadı.")
    return m.group(1)


def main():
    if len(sys.argv) < 2 or not Path(sys.argv[1]).is_file():
        sys.exit("Kullanım: py yayinla.py notlar.md")
    notes = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    ver = version()
    tag = f"v{ver}"

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit("Commit'lenmemiş değişiklikler var. Önce commit'le ve gönder (git push).")
    if subprocess.run(["gh", "release", "view", tag], cwd=ROOT, capture_output=True).returncode == 0:
        sys.exit(f"{tag} zaten yayınlanmış. yakala/config.py içinde APP_VERSION'ı yükselt.")

    deno = subprocess.run([sys.executable, "-c", "import deno; print(deno.find_deno_bin())"],
                          capture_output=True, text=True, check=True).stdout.strip()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
         "--log-level", "WARN", "--name", "Yakala", "--icon", "yakala/web/icon.ico",
         "--add-data", "yakala/web;yakala/web", "--add-binary", f"{deno};bin",
         *[a for pkg in ("yt_dlp", "yt_dlp_ejs", "gallery_dl", "webview", "imageio_ffmpeg", "curl_cffi", "segno")
           for a in ("--collect-all", pkg)],
         "Yakala.pyw"])

    out = ROOT / "dist" / f"Yakala-{ver}-windows.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for d, _, files in os.walk(ROOT / "dist" / "Yakala"):
            for f in files:
                p = Path(d) / f
                z.write(p, p.relative_to(ROOT / "dist"))
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"Paket: {out.name} ({out.stat().st_size / 1e6:.0f} MB)  SHA-256: {sha}")

    body = ROOT / "dist" / "release-notes.md"
    body.write_text(f"{notes}\n\nSHA-256: `{sha}`\n", encoding="utf-8")
    run(["gh", "release", "create", tag, str(out), "--title", f"Yakala {ver}", "--latest", "--notes-file", str(body)])
    print(f"\nYayınlandı: {tag}. Kullanıcılardaki Yakala en geç birkaç saat içinde bu sürümü kendiliğinden kurar.")


if __name__ == "__main__":
    if shutil.which("gh") is None:
        sys.exit("GitHub CLI (gh) bulunamadı: https://cli.github.com")
    main()
