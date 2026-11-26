"""Yakala giriş noktası.

Yardımcı kipler (alt süreç olarak çağrılır):
  --gallery-dl ARGS...   gallery-dl'yi çalıştırır
  --pick-folder [YOL]    klasör seçme penceresi
  --pick-file [YOL]      dosya seçme penceresi (cookies.txt)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def _picker(kind: str, initial: str):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if kind == "folder":
        path = filedialog.askdirectory(initialdir=initial or None, title="İndirme klasörünü seç", mustexist=False)
    else:
        path = filedialog.askopenfilename(
            initialdir=os.path.dirname(initial) if initial else None,
            title="cookies.txt dosyasını seç",
            filetypes=[("Çerez dosyası", "*.txt"), ("Tüm dosyalar", "*.*")],
        )
    root.destroy()
    sys.stdout.write(os.path.normpath(path) if path else "")
    sys.stdout.flush()


def _find_browser() -> str | None:
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("msedge") or shutil.which("chrome")


def _setup_logging():
    """Hataları %APPDATA%\\Yakala\\yakala.log dosyasına yaz (pencereli uygulamada konsol yok)."""
    import faulthandler
    import logging
    import threading
    from logging.handlers import RotatingFileHandler

    from . import config

    path = config.app_dir() / "yakala.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("yakala")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.info("Yakala %s başladı", config.APP_VERSION)
    try:
        faulthandler.enable(open(config.app_dir() / "yakala-crash.log", "a", encoding="utf-8"))  # noqa: SIM115
    except OSError:
        pass
    sys.excepthook = lambda t, v, tb: root.critical("Yakalanmamış hata", exc_info=(t, v, tb))
    threading.excepthook = lambda a: root.error("İş parçacığında hata (%s)", a.thread and a.thread.name,
                                                exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def _single_instance() -> bool:
    """Yakala zaten açıksa onun penceresini öne getir ve False döndür."""
    if os.name != "nt":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\YakalaTekOrnek")
    globals()["_mutex"] = handle  # süreç boyunca açık kalsın
    if kernel32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return True
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "Yakala")
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return False


def run_app():
    from . import config, server

    _setup_logging()
    if "--serve" not in sys.argv and not _single_instance():
        return
    app = server.App()
    port = 0
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv, port = server.start(app, port)
    url = f"http://127.0.0.1:{port}/"
    if "--serve" in sys.argv:
        print(url, flush=True)
        server.wait_forever()
        return
    if "--browser" in sys.argv:
        import webbrowser

        webbrowser.open(url)
        server.wait_forever()
        return

    try:
        import webview  # type: ignore

        icon = config.resource_dir() / "web" / "icon.ico"
        window = webview.create_window(
            "Yakala", url, width=1200, height=800, min_size=(900, 620),
            background_color="#191530", text_select=True,
        )
        app.window = window
        webview.start(private_mode=False, storage_path=str(config.app_dir() / "webview"),
                      icon=str(icon) if icon.exists() else None)
        srv.shutdown()
        return
    except Exception:
        pass

    browser = _find_browser()
    if browser:
        profile = config.app_dir() / "browser-profile"
        proc = subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}",
                                 "--window-size=1200,800", "--no-first-run", "--no-default-browser-check"])
        proc.wait()
        srv.shutdown()
        return
    import webbrowser

    webbrowser.open(url)
    server.wait_forever()


def main():
    args = sys.argv[1:]
    if args and args[0] == "--engine-test":
        from . import updater

        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
        sys.exit(updater.engine_test(args[1]))
    from . import updater

    updater.activate()
    if args and args[0] == "--gallery-dl":
        import gallery_dl

        sys.argv = ["gallery-dl", *args[1:]]
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
        sys.exit(gallery_dl.main())
    if args and args[0] in ("--pick-folder", "--pick-file"):
        _picker("folder" if args[0] == "--pick-folder" else "file", args[1] if len(args) > 1 else "")
        return
    run_app()


if __name__ == "__main__":
    main()
