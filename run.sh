#!/bin/bash
# Run PrtSc AI from source on macOS (no build). Needs Python 3.10+ (python.org or Homebrew).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
# Note: macOS asks for Screen Recording permission for the app that runs Python
# (your Terminal) when you run from source.
exec .venv/bin/python main.py
