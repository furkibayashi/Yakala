@echo off
REM Yakala icin gereken paketleri kurar.
cd /d "%~dp0"
py -m pip install -U -r requirements.txt
echo.
echo Kurulum tamam. Baslatmak icin Yakala.pyw dosyasina cift tikla.
pause
