@echo off
REM Yakala.exe derleme betigi (Windows). Gereksinim: Python 3.10+
cd /d "%~dp0"
py -m pip install -r requirements.txt pyinstaller
for /f "delims=" %%i in ('py -c "import deno; print(deno.find_deno_bin())"') do set DENO=%%i
py -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name Yakala ^
  --icon yakala\web\icon.ico ^
  --add-data "yakala\web;yakala\web" ^
  --add-binary "%DENO%;bin" ^
  --collect-all yt_dlp ^
  --collect-all yt_dlp_ejs ^
  --collect-all gallery_dl ^
  --collect-all webview ^
  --collect-all imageio_ffmpeg ^
  --collect-all curl_cffi ^
  Yakala.pyw
echo.
echo Hazir: dist\Yakala\Yakala.exe
pause
