"""macOS plumbing: global hotkey, Screen Recording permission, screenshot-folder
watcher, open-at-login and a few window tweaks.

Everything talks to the system frameworks through ctypes (no pyobjc), and the
module imports cleanly on any OS so the pure-Python parts can be tested anywhere.

* Hotkey: Carbon RegisterEventHotKey. It's what most Mac apps use for global
  shortcuts and, unlike an event tap, needs no Accessibility permission.
* macOS screenshots (Shift+Cmd+3/4/5) are saved as FILES (Desktop by default, or
  wherever `defaults read com.apple.screencapture location` points), so we watch
  that folder. Ctrl+Shift+Cmd+4 copies to the clipboard, which main.py already watches.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QImage

IS_MAC = sys.platform == "darwin"

DEFAULT_HOTKEY = "Cmd+Shift+1"
BUNDLE_ID = "com.aagams06.prtscai"
PRIVACY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".tiff", ".tif", ".gif", ".bmp", ".webp"}

# Carbon modifier bits (Events.h)
CMD, SHIFT, OPTION, CONTROL = 0x100, 0x200, 0x800, 0x1000

# kVK_* virtual key codes (Events.h) for the keys people put in shortcuts
_KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06,
    "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
    "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D,
    "m": 0x2E, "space": 0x31,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
    "f13": 0x69, "f14": 0x6B, "f15": 0x71, "f16": 0x6A, "f17": 0x40, "f18": 0x4F,
    "f19": 0x50, "f20": 0x5A,
}
_SYMBOLS = {"⌘": "cmd", "⇧": "shift", "⌥": "option", "⌃": "ctrl"}


# =============================================================== hotkey text
def _tokens(text: str) -> list[str]:
    for sym, name in _SYMBOLS.items():
        text = text.replace(sym, f"+{name}+")
    return [p.strip().lower() for p in text.replace(" ", "+").split("+") if p.strip()]


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Cmd+Shift+1', 'Command+Shift+1' or '⇧⌘1' -> (carbon modifiers, key code)."""
    mods, key = 0, None
    for part in _tokens(text):
        if part in ("cmd", "command", "meta", "super", "win"):
            mods |= CMD
        elif part == "shift":
            mods |= SHIFT
        elif part in ("alt", "opt", "option"):
            mods |= OPTION
        elif part in ("ctrl", "control"):
            mods |= CONTROL
        elif part in _KEYCODES and key is None:
            key = _KEYCODES[part]
        else:
            return None
    if key is None or mods == 0:
        return None
    return mods, key


def hotkey_label(text: str) -> str:
    """'Cmd+Shift+1' -> '⇧⌘1' (Apple's modifier order ⌃⌥⇧⌘)."""
    if parse_hotkey(text) is None:
        return text
    parts = _tokens(text)
    mods = {"ctrl": "⌃", "control": "⌃", "alt": "⌥", "opt": "⌥", "option": "⌥",
            "shift": "⇧", "cmd": "⌘", "command": "⌘", "meta": "⌘", "super": "⌘", "win": "⌘"}
    sym = "".join(s for s in "⌃⌥⇧⌘" if any(mods.get(p) == s for p in parts))
    key = next(p for p in parts if p not in mods)
    return sym + ("Space" if key == "space" else key.upper())


def looks_like_snip() -> bool:
    """macOS doesn't say which app put an image on the clipboard, so a clipboard
    image (e.g. Ctrl+Shift+Cmd+4) always counts. Saved screenshots are filtered
    in ScreenshotWatcher instead."""
    return True


# =============================================================== Objective-C bits
_objc = None


def _load_objc():
    global _objc
    if _objc is None and IS_MAC:
        ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.dylib")
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return _objc


def _send(obj, sel: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """objc_msgSend with an exact prototype (required on Apple Silicon)."""
    objc = _load_objc()
    fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(
        ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value)
    return fn(obj, objc.sel_registerName(sel.encode()), *args)


def _nsapp():
    return _send(_load_objc().objc_getClass(b"NSApplication"), "sharedApplication")


def set_accessory_app() -> None:
    """Menu-bar only, no Dock icon. The packaged .app gets this from LSUIElement;
    this covers running from source."""
    if not IS_MAC:
        return
    try:
        _send(_nsapp(), "setActivationPolicy:", 1, restype=ctypes.c_bool, argtypes=(ctypes.c_long,))
    except Exception:
        pass


def activate_app() -> None:
    """A menu-bar app isn't 'active' by default; do this before showing a window."""
    if not IS_MAC:
        return
    try:
        _send(_nsapp(), "activateIgnoringOtherApps:", True, restype=None, argtypes=(ctypes.c_bool,))
    except Exception:
        pass


def float_above_everything(widget) -> None:
    """Put a window above the menu bar and over full-screen apps (snip overlay)."""
    if not IS_MAC:
        return
    try:
        view = ctypes.c_void_p(int(widget.winId()))
        win = _send(view, "window")
        if win:
            _send(win, "setLevel:", 1000, restype=None, argtypes=(ctypes.c_long,))  # screen-saver level
            # canJoinAllSpaces | fullScreenAuxiliary
            _send(win, "setCollectionBehavior:", (1 << 0) | (1 << 8), restype=None,
                  argtypes=(ctypes.c_ulong,))
    except Exception:
        pass


# =============================================================== Screen Recording
def _cg():
    return ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")


def has_screen_recording() -> bool:
    if not IS_MAC:
        return True
    try:
        f = _cg().CGPreflightScreenCaptureAccess
        f.restype = ctypes.c_bool
        return bool(f())
    except Exception:
        return True  # macOS < 10.15: no such permission


def request_screen_recording() -> bool:
    """Shows macOS's own prompt the first time; afterwards just returns the state."""
    if not IS_MAC:
        return True
    try:
        f = _cg().CGRequestScreenCaptureAccess
        f.restype = ctypes.c_bool
        return bool(f())
    except Exception:
        return True


def open_privacy_pane() -> None:
    subprocess.Popen(["open", PRIVACY_PANE])


# =============================================================== global hotkey
class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_carbon = None


def _load_carbon():
    global _carbon
    if _carbon is None:
        c = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_ulong,
                                          ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.InstallEventHandler.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_void_p)]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.UnregisterEventHotKey.restype = ctypes.c_int32
        _carbon = c
    return _carbon


class GlobalHotkey(QObject):
    """Carbon hot key. Events arrive on the main thread through Qt's Cocoa loop."""
    triggered = pyqtSignal()
    failed = pyqtSignal(str)

    _handler_ref = None   # keep the ctypes callback alive for the whole process
    _instances: list = []

    def __init__(self) -> None:
        super().__init__()
        self._ref = ctypes.c_void_p()
        GlobalHotkey._instances.append(self)

    @classmethod
    def _on_event(cls, _call, _event, _data) -> int:
        for inst in cls._instances:
            if inst._ref:
                QTimer.singleShot(0, inst.triggered.emit)
        return 0

    def start(self, text: str) -> bool:
        self.stop()
        if not IS_MAC:
            return False
        parsed = parse_hotkey(text)
        if not parsed:
            self.failed.emit(f"Can't understand hotkey '{text}'. Use e.g. Cmd+Shift+1.")
            return False
        mods, key = parsed
        try:
            c = _load_carbon()
            if GlobalHotkey._handler_ref is None:
                spec = _EventTypeSpec(0x6B657962, 5)  # 'keyb', kEventHotKeyPressed
                cb = _HANDLER(GlobalHotkey._on_event)
                err = c.InstallEventHandler(c.GetApplicationEventTarget(), cb, 1,
                                            ctypes.byref(spec), None, None)
                if err:
                    raise OSError(err)
                GlobalHotkey._handler_ref = cb
            err = c.RegisterEventHotKey(key, mods, _EventHotKeyID(0x50725363, 1),  # 'PrSc'
                                        c.GetApplicationEventTarget(), 0, ctypes.byref(self._ref))
        except Exception as e:  # noqa: BLE001
            err = getattr(e, "args", [str(e)])[0]
        if err or not self._ref:
            self._ref = ctypes.c_void_p()
            self.failed.emit(f"{hotkey_label(text)} is already used by macOS or another app. "
                             "Pick a different hotkey in Settings.")
            return False
        return True

    def stop(self) -> None:
        if IS_MAC and self._ref:
            try:
                _load_carbon().UnregisterEventHotKey(self._ref)
            except Exception:
                pass
        self._ref = ctypes.c_void_p()


# =============================================================== screenshots folder
def screenshot_folder() -> Path:
    """Where Shift+Cmd+3/4/5 save files (System default: the Desktop)."""
    default = Path.home() / "Desktop"
    if not IS_MAC:
        return default
    try:
        out = subprocess.run(["defaults", "read", "com.apple.screencapture", "location"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        out = ""
    p = Path(os.path.expanduser(out)) if out else default
    return p if p.is_dir() else default


def screenshot_name_prefix() -> str:
    """The user's custom screenshot file name, if they set one."""
    if not IS_MAC:
        return ""
    try:
        return subprocess.run(["defaults", "read", "com.apple.screencapture", "name"],
                              capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ""


# localized default names ("Screenshot", "Screen Shot" on older macOS, ...)
_NAME_HINTS = ("screenshot", "screen shot", "bildschirmfoto", "capture d", "captura de pantalla",
               "schermata", "skärmavbild", "schermafbeelding", "zrzut ekranu", "снимок экрана",
               "スクリーンショット", "截屏", "螢幕截圖", "스크린샷", "skjermbilde", "näyttökuva")


def _has_screenshot_xattr(path: Path) -> bool:
    if not IS_MAC:
        return False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.getxattr.restype = ctypes.c_ssize_t
        libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        n = libc.getxattr(os.fsencode(str(path)), b"com.apple.metadata:kMDItemIsScreenCapture",
                          None, 0, 0, 0)
        return n >= 0
    except Exception:
        return False


def is_screenshot_file(path: Path, custom_prefix: str = "") -> bool:
    """macOS tags screenshots with kMDItemIsScreenCapture; the name is a fallback."""
    name = path.name.lower()
    if custom_prefix and name.startswith(custom_prefix.lower()):
        return True
    return _has_screenshot_xattr(path) or any(h in name for h in _NAME_HINTS)


class ScreenshotWatcher(QObject):
    """Emits each NEW image file that shows up in the screenshot folder."""
    captured = pyqtSignal(QImage, str)

    def __init__(self, folder: Path | None = None, only_screenshots: bool = True) -> None:
        super().__init__()
        self.only_screenshots = only_screenshots
        self.folder: Path | None = None
        self._seen: set[str] = set()
        self._ignore: set[str] = set()
        self._pending: dict[str, int] = {}
        self._prefix = ""
        self._since = time.time()
        self._fs = QFileSystemWatcher(self)
        self._fs.directoryChanged.connect(lambda _p: self._scan())
        self._poll = QTimer(self, interval=250)
        self._poll.timeout.connect(self._check_pending)
        self.set_folder(folder or screenshot_folder())

    def set_folder(self, folder: Path) -> None:
        if self._fs.directories():
            self._fs.removePaths(self._fs.directories())
        self.folder = Path(folder)
        self._prefix = screenshot_name_prefix()
        self._seen = {str(p) for p in self._list()}  # only files created from now on count
        self._since = time.time() - 1
        if self.folder.is_dir():
            self._fs.addPath(str(self.folder))

    def ignore(self, path: str) -> None:
        """Files we write ourselves (e.g. 'Save image') never pop a bubble."""
        self._ignore.add(str(Path(path)))

    def _list(self) -> list[Path]:
        try:
            return [p for p in self.folder.iterdir()
                    if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")]
        except Exception:
            return []

    def _scan(self) -> None:
        for p in self._list():
            s = str(p)
            if s in self._seen or s in self._pending:
                continue
            self._seen.add(s)
            try:
                if p.stat().st_mtime < self._since:
                    continue  # an old file moved/renamed into the folder
            except OSError:
                continue
            if s in self._ignore:
                continue
            self._pending[s] = -1
        if self._pending and not self._poll.isActive():
            self._poll.start()

    def _check_pending(self) -> None:
        """Wait until the file stops growing, then load it once."""
        for s in list(self._pending):
            p = Path(s)
            try:
                size = p.stat().st_size
            except OSError:
                self._pending.pop(s)
                continue
            if size == 0 or size != self._pending[s]:
                self._pending[s] = size
                continue
            self._pending.pop(s)
            if self.only_screenshots and not is_screenshot_file(p, self._prefix):
                continue
            img = QImage(s)
            if not img.isNull():
                self.captured.emit(img, s)
        if not self._pending:
            self._poll.stop()


# =============================================================== open at login
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"


def _launch_command() -> list[str] | None:
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        # Not from a disk image or Gatekeeper's temporary copy: those paths vanish.
        if exe.startswith("/Volumes/") or "/AppTranslocation/" in exe:
            return None
        return [exe]
    return [str(Path(sys.executable).resolve()), str(Path(__file__).with_name("main.py").resolve())]


def set_open_at_login(enabled: bool, agent: Path = LAUNCH_AGENT) -> bool:
    """(Re)point a LaunchAgent at THIS app, so a newer copy takes over at login.
    Returns True if the file now matches the request."""
    if not enabled:
        try:
            agent.unlink()
        except FileNotFoundError:
            pass
        return True
    cmd = _launch_command()
    if cmd is None:
        return False
    plist = {"Label": BUNDLE_ID, "ProgramArguments": cmd, "RunAtLoad": True,
             "ProcessType": "Interactive", "LimitLoadToSessionType": "Aqua"}
    data = plistlib.dumps(plist)
    try:
        if agent.exists() and agent.read_bytes() == data:
            return True
        agent.parent.mkdir(parents=True, exist_ok=True)
        tmp = agent.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(agent)
        return True
    except OSError:
        return False
