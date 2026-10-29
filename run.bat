@echo off
REM Run PrtSc AI from source (no build). Needs Python 3.10+ installed.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe main.py
