"""Windows-only plumbing: global hotkey + "who put this on the clipboard?".
Everything degrades to a harmless no-op on other OSes so the UI can be tested."""
from __future__ import annotations

import os
import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetClipboardOwner.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Processes that own the clipboard after a Win+Shift+S / PrtSc snip.
SNIP_PROCESSES = {"screenclippinghost.exe", "snippingtool.exe", "screensketch.exe"}


def clipboard_owner_process() -> str | None:
    """Lower-case exe name of the clipboard owner, or None if unknown."""
    if not IS_WIN:
        return None
    hwnd = user32.GetClipboardOwner()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)
    return None


def looks_like_snip() -> bool:
    """True if the current clipboard image probably came from the Windows snip tool.
    Unknown owner (window already closed, legacy PrtSc) counts as a snip;
    a known other app (browser, Paint, ...) does not."""
    owner = clipboard_owner_process()
    return owner is None or owner in SNIP_PROCESSES


def parse_hotkey(text: str) -> tuple[int, int] | None:
    mods, vk = 0, None
    for part in [p.strip().lower() for p in text.split("+") if p.strip()]:
        if part in ("win", "windows", "meta", "super"):
            mods |= MOD_WIN
        elif part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "alt":
            mods |= MOD_ALT
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        else:
            return None
    if vk is None or mods == 0:
        return None
    return mods, vk


class GlobalHotkey(QObject):
    """RegisterHotKey on a background thread with its own message loop."""
    triggered = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._tid = 0

    def start(self, text: str) -> None:
        self.stop()
        if not IS_WIN:
            return
        parsed = parse_hotkey(text)
        if not parsed:
            self.failed.emit(f"Can't understand hotkey '{text}'. Use e.g. Win+Shift+A.")
            return
        mods, vk = parsed
        ready = threading.Event()

        def run():
            self._tid = kernel32.GetCurrentThreadId()
            ok = user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk)
            ready.set()
            if not ok:
                self.failed.emit(f"{text} is already used by Windows or another app. "
                                 "Pick a different hotkey in Settings.")
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.triggered.emit()
            user32.UnregisterHotKey(None, 1)

        self._thread = threading.Thread(target=run, daemon=True, name="hotkey")
        self._thread.start()
        ready.wait(2)

    def stop(self) -> None:
        if IS_WIN and self._thread and self._thread.is_alive() and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(1)
        self._thread, self._tid = None, 0
