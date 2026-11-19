@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo Brak programu uv. Zainstaluj go lub zbuduj aplikacje recznie przez PyInstaller.
  pause
  exit /b 1
)

uv venv .venv
if errorlevel 1 exit /b 1
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 exit /b 1

.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name GIF-160x128 --collect-all tkinterdnd2 app.py
if errorlevel 1 exit /b 1

copy /Y "dist\GIF-160x128.exe" "GIF-160x128.exe" >nul
if errorlevel 1 exit /b 1

echo.
echo Gotowe: GIF-160x128.exe
pause
