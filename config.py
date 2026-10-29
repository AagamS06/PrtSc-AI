"""Settings storage. Non-secret settings -> JSON in %APPDATA%\\PrtSc AI.
API keys -> Windows Credential Manager (via keyring), never in the JSON."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import keyring
except Exception:  # keyring missing or no backend
    keyring = None

APP_NAME = "PrtSc AI"
KEYRING_SERVICE = "PrtSc AI"

if sys.platform == "win32":
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
else:
    CONFIG_DIR = Path.home() / ".config" / "prtsc-ai"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "provider": "Gemini (Google)",
    # per-provider remembered base_url / model
    "providers": {},
    "bubble_enabled": True,
    "bubble_timeout": 3,         # seconds, 1-10
    "bubble_snips_only": True,   # only pop for Windows snip tool copies
    "hotkey": "Win+Shift+A",
    "start_with_windows": True,
    "first_run": True,
}


class Config:
    def __init__(self) -> None:
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            if CONFIG_FILE.exists():
                self.data.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except Exception:
            pass
        self.data["bubble_timeout"] = max(1, min(10, int(self.data.get("bubble_timeout", 3))))

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.data, indent=2), "utf-8")

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    # --- per-provider fields
    def provider_field(self, provider: str, field: str, default: str = "") -> str:
        return self.data["providers"].get(provider, {}).get(field, default)

    def set_provider_field(self, provider: str, field: str, value: str) -> None:
        self.data["providers"].setdefault(provider, {})[field] = value

    # --- secrets
    @staticmethod
    def get_key(provider: str) -> str:
        if keyring is None:
            return ""
        try:
            return keyring.get_password(KEYRING_SERVICE, provider) or ""
        except Exception:
            return ""

    @staticmethod
    def set_key(provider: str, key: str) -> None:
        if keyring is None:
            return
        try:
            if key:
                keyring.set_password(KEYRING_SERVICE, provider, key)
            else:
                keyring.delete_password(KEYRING_SERVICE, provider)
        except Exception:
            pass


def set_start_with_windows(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = pyw if pyw.exists() else Path(sys.executable)
        cmd = f'"{exe}" "{Path(__file__).with_name("main.py").resolve()}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass
