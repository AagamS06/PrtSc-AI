"""Settings storage that survives updates.

Everything lives in the OS, never inside the .exe/.app, so any newer download
(wherever it's saved) picks up the previous version's setup.

Windows:

  * Settings (provider, model, hotkey, bubble...) -> %APPDATA%\\PrtSc AI\\settings.json
  * API keys -> Windows Credential Manager ("PrtSc AI:<provider>"), written with
    the Win32 API directly (no plugin discovery that can break in a packaged exe).
    If Credential Manager refuses, the key is encrypted with Windows DPAPI
    (only your Windows account can decrypt it) and kept in settings.json.
  * Keys saved by v1.0.0 (via the keyring library) are found and migrated
    automatically the first time they're needed.

macOS:
  * Settings -> ~/Library/Application Support/PrtSc AI/settings.json
  * API keys -> the login Keychain (service "PrtSc AI", account = provider), via
    keyring's macOS backend imported directly (no entry-point discovery).
  * Open at login -> a LaunchAgent in ~/Library/LaunchAgents, re-pointed at the
    running .app on every launch.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

APP_NAME = "PrtSc AI"
SERVICE = "PrtSc AI"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

if IS_WIN:
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
elif IS_MAC:
    CONFIG_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
else:
    CONFIG_DIR = Path.home() / ".config" / "prtsc-ai"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "provider": "Gemini (Google)",
    # per-provider remembered base_url / model
    "providers": {},
    "bubble_enabled": True,
    "bubble_timeout": 3,         # seconds, 1-10
    "bubble_snips_only": True,   # only pop for Windows snips / macOS screenshots
    "hotkey": "Cmd+Shift+1" if IS_MAC else "Win+Shift+A",
    "start_with_windows": True,  # "Open at login" on macOS
    "mac_permission_shown": False,
    "first_run": True,
    "enc_keys": {},              # DPAPI fallback only
}


# =============================================================== Win32 secrets
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCRED = ctypes.POINTER(_CREDENTIAL)
    _advapi.CredWriteW.argtypes = [_PCRED, wintypes.DWORD]
    _advapi.CredWriteW.restype = wintypes.BOOL
    _advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCRED)]
    _advapi.CredReadW.restype = wintypes.BOOL
    _advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi.CredDeleteW.restype = wintypes.BOOL
    _advapi.CredFree.argtypes = [ctypes.c_void_p]

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    _crypt.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    _crypt.CryptProtectData.restype = wintypes.BOOL
    _crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    _crypt.CryptUnprotectData.restype = wintypes.BOOL
    _kernel.LocalFree.argtypes = [ctypes.c_void_p]


def _cred_read(target: str) -> tuple[str, str] | None:
    """(username, secret) for a generic credential, or None."""
    if not IS_WIN:
        return None
    p = _PCRED()
    if not _advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        try:
            secret = raw.decode("utf-16-le")
        except UnicodeDecodeError:
            secret = raw.decode("utf-8", "replace")
        return (c.UserName or "", secret)
    finally:
        _advapi.CredFree(p)


def _cred_write(target: str, username: str, secret: str) -> bool:
    if not IS_WIN:
        return False
    data = secret.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    c = _CREDENTIAL()
    c.Type = CRED_TYPE_GENERIC
    c.TargetName = target
    c.UserName = username
    c.Comment = "PrtSc AI API key"
    c.CredentialBlobSize = len(data)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    return bool(_advapi.CredWriteW(ctypes.byref(c), 0))


def _cred_delete(target: str) -> None:
    if IS_WIN:
        _advapi.CredDeleteW(target, CRED_TYPE_GENERIC, 0)


def _dpapi(data: bytes, protect: bool) -> bytes | None:
    """Encrypt/decrypt with Windows DPAPI (tied to the current Windows user)."""
    if not IS_WIN or not data:
        return None
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    inp = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out = _BLOB()
    if protect:
        ok = _crypt.CryptProtectData(ctypes.byref(inp), "PrtSc AI", None, None, None, 0, ctypes.byref(out))
    else:
        ok = _crypt.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel.LocalFree(out.pbData)


# =============================================================== macOS Keychain
_kc = [None]


def _keychain():
    """keyring's macOS backend, imported directly (no plugin discovery)."""
    if not IS_MAC:
        return None
    if _kc[0] is None:
        from keyring.backends.macOS import Keyring
        _kc[0] = Keyring()
    return _kc[0]


def _kc_get(provider: str) -> str:
    try:
        return _keychain().get_password(SERVICE, provider) or ""
    except Exception:
        return ""


def _kc_set(provider: str, key: str) -> bool:
    try:
        _keychain().set_password(SERVICE, provider, key)
        return _kc_get(provider) == key
    except Exception:
        return False


def _kc_delete(provider: str) -> None:
    try:
        _keychain().delete_password(SERVICE, provider)
    except Exception:
        pass


def _target(provider: str) -> str:
    return f"{SERVICE}:{provider}"


def _legacy_key(provider: str) -> str:
    """Keys saved by v1.0.0 through the keyring library."""
    # keyring's Windows backend stores the first user under "<service>",
    # and any other user under "<user>@<service>".
    for target in (f"{provider}@{SERVICE}", SERVICE):
        hit = _cred_read(target)
        if hit and hit[0] == provider and hit[1]:
            return hit[1]
    if IS_MAC:
        return ""  # the Keychain IS the store on macOS; nothing to migrate
    try:  # last resort: ask keyring itself (non-Windows dev runs, odd backends)
        import keyring
        return keyring.get_password(SERVICE, provider) or ""
    except Exception:
        return ""


# =============================================================== Config
class Config:
    def __init__(self) -> None:
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            if CONFIG_FILE.exists():
                self.data.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except Exception:
            # corrupt file: keep a copy so nothing is silently lost
            try:
                CONFIG_FILE.replace(CONFIG_FILE.with_suffix(".broken.json"))
            except Exception:
                pass
        self.data["bubble_timeout"] = max(1, min(10, int(self.data.get("bubble_timeout", 3))))
        self.data.setdefault("enc_keys", {})
        _active[0] = self

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), "utf-8")
        tmp.replace(CONFIG_FILE)  # atomic: an update/crash can't leave half a file

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    # --- per-provider fields
    def provider_field(self, provider: str, field: str, default: str = "") -> str:
        return self.data["providers"].get(provider, {}).get(field, default)

    def set_provider_field(self, provider: str, field: str, value: str) -> None:
        self.data["providers"].setdefault(provider, {})[field] = value

    def saved_providers(self) -> list[str]:
        """Providers that already have a key stored (any version)."""
        from providers import PRESETS
        return [p.name for p in PRESETS if p.needs_key and Config.get_key(p.name)]

    # --- secrets
    @staticmethod
    def get_key(provider: str) -> str:
        if IS_MAC:
            return _kc_get(provider)
        hit = _cred_read(_target(provider))
        if hit and hit[1]:
            return hit[1]
        cfg = _active[0]
        if cfg is not None:
            enc = cfg.data.get("enc_keys", {}).get(provider)
            if enc:
                raw = _dpapi(base64.b64decode(enc), protect=False)
                if raw:
                    return raw.decode("utf-8")
        old = _legacy_key(provider)
        if old:
            Config.set_key(provider, old)  # migrate to the new store
        return old

    @staticmethod
    def set_key(provider: str, key: str) -> bool:
        """Store (or clear) a key. Returns True if it is persisted."""
        cfg = _active[0]
        if IS_MAC:
            if not key:
                _kc_delete(provider)
                return True
            return _kc_set(provider, key)
        if not key:
            _cred_delete(_target(provider))
            if cfg is not None and cfg.data.get("enc_keys", {}).pop(provider, None) is not None:
                cfg.save()
            return True
        if _cred_write(_target(provider), provider, key) and \
                (_cred_read(_target(provider)) or ("", ""))[1] == key:
            if cfg is not None and cfg.data.get("enc_keys", {}).pop(provider, None) is not None:
                cfg.save()
            return True
        enc = _dpapi(key.encode("utf-8"), protect=True)
        if enc and cfg is not None:
            cfg.data.setdefault("enc_keys", {})[provider] = base64.b64encode(enc).decode()
            cfg.save()
            return True
        if not IS_WIN:  # dev runs on Linux/macOS
            try:
                import keyring
                keyring.set_password(SERVICE, provider, key)
                return True
            except Exception:
                return False
        return False


_active: list[Config | None] = [None]


def set_start_with_windows(enabled: bool) -> None:
    """(Re)point the login entry at THIS exe/.app, so a newer download replaces the old one.
    On macOS this is a LaunchAgent ("Open at login")."""
    if IS_MAC:
        from macsys import set_open_at_login
        set_open_at_login(enabled)
        return
    if not IS_WIN:
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


def selftest() -> int:
    """Round-trip a key through the real store. Used by CI on the built exe."""
    name = "__selftest__"
    cfg = Config()
    try:
        ok = Config.set_key(name, "sk-test-123") and Config.get_key(name) == "sk-test-123"
        if IS_MAC:  # must really be in the Keychain, and clearing must work
            ok = ok and _kc_get(name) == "sk-test-123"
            ok = ok and Config.set_key(name, "") and Config.get_key(name) == ""
        # simulate a v1.0.0 keyring entry and make sure it migrates
        if IS_WIN:
            _cred_write(f"{name}2@{SERVICE}", f"{name}2", "legacy-456")
            ok = ok and Config.get_key(f"{name}2") == "legacy-456" \
                and (_cred_read(_target(f"{name}2")) or ("", ""))[1] == "legacy-456"
        return 0 if ok else 1
    finally:
        Config.set_key(name, "")
        Config.set_key(f"{name}2", "")
        _cred_delete(f"{name}2@{SERVICE}")
        cfg.data.get("enc_keys", {}).clear()
