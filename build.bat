@echo off
REM Build a single PrtSc-AI.exe in the dist folder. Needs Python 3.10+ installed.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt pyinstaller pillow
.venv\Scripts\python make_icon.py
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name PrtSc-AI --icon assets\icon.ico --hidden-import keyring.backends.Windows main.py
echo.
echo Done. Your app is at dist\PrtSc-AI.exe
pause
