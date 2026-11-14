"""PrtSc AI — Circle-to-Search for Windows and macOS.

Windows:
* Win+Shift+S / PrtSc snip  -> "AI" bubble pops next to the cursor (timeout 1-10 s)
* Win+Shift+A               -> straight to an AI snip, no bubble
* Tray icon                 -> snip, settings, pause bubble, quit

macOS:
* Shift+Cmd+3/4/5 screenshot (saved file) or Ctrl+Shift+Cmd+4 (clipboard) -> same bubble
* Shift+Cmd+1               -> straight to an AI snip
* Menu-bar icon             -> same menu as the Windows tray
"""
from __future__ import annotations

import hashlib
import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QGuiApplication, QImage
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import Config, set_start_with_windows
from ui import Bubble, ChatWindow, SettingsDialog, SnipOverlay, app_icon

IS_MAC = sys.platform == "darwin"
if IS_MAC:
    import macsys as osys
else:
    import winsys as osys

__version__ = "1.1.0"
SINGLETON = "PrtSc-AI-singleton"


class App:
    def __init__(self, qapp: QApplication) -> None:
        self.qapp = qapp
        self.cfg = Config()
        self.chats: list[ChatWindow] = []
        self.settings: SettingsDialog | None = None
        self._last_hash = b""
        self._last_time = 0.0
        self._perm_dialog = None

        self.bubble = Bubble()
        self.bubble.ask.connect(self.open_chat)
        self.overlay = SnipOverlay()
        self.overlay.captured.connect(self.open_chat)

        # clipboard watcher (debounced — the snip tool can write more than once)
        self._debounce = QTimer(singleShot=True, interval=150)
        self._debounce.timeout.connect(self._check_clipboard)
        QGuiApplication.clipboard().dataChanged.connect(self._debounce.start)

        # macOS screenshots are saved as files: watch the screenshot folder too
        self.watcher = None
        if IS_MAC:
            self.watcher = osys.ScreenshotWatcher(only_screenshots=self.cfg["bubble_snips_only"])
            self.watcher.captured.connect(lambda img, _path: self._offer(img))

        # global hotkey
        self.hotkey = osys.GlobalHotkey()
        self.hotkey.triggered.connect(self.start_snip)
        self.hotkey.failed.connect(lambda m: self.tray.showMessage("PrtSc AI", m))

        self._build_tray()
        self.hotkey.start(self.cfg["hotkey"])

        # Always point "start with Windows" at THIS exe, so a newer download takes over.
        try:
            set_start_with_windows(self.cfg["start_with_windows"])
        except Exception:
            pass

        if IS_MAC and not osys.has_screen_recording():
            # macOS shows its own prompt the first time; ours explains where the switch is
            osys.request_screen_recording()
            if not self.cfg["mac_permission_shown"]:
                self.cfg["mac_permission_shown"] = True
                QTimer.singleShot(800, self.show_permission_help)

        prev = self.cfg.data.get("last_version")
        has_key = bool(Config.get_key(self.cfg["provider"])) or not self._needs_key()
        if prev and prev != __version__:
            self.tray.showMessage(
                f"PrtSc AI updated to v{__version__}",
                "Your settings and API keys were carried over from your previous version.")
        elif self.cfg["first_run"] and not has_key:
            if IS_MAC:
                tip = (f"Take a screenshot (⇧⌘4) and click the AI bubble, "
                       f"or press {self._hk_label()}.")
            else:
                tip = f"Snip with Win+Shift+S and click the AI bubble, or press {self.cfg['hotkey']}."
            self.tray.showMessage("PrtSc AI is running", tip)
        if not has_key:
            QTimer.singleShot(400, self.show_settings)
        else:
            self.cfg["first_run"] = False
        self.cfg["last_version"] = __version__
        try:
            self.cfg.save()
        except Exception:
            pass

    def _hk_label(self) -> str:
        return osys.hotkey_label(self.cfg["hotkey"])

    def _snip_text(self) -> str:
        # macOS menus don't do tab-aligned shortcuts for plain text, so show it inline
        return f"Snip with AI   {self._hk_label()}" if IS_MAC else f"Snip with AI\t{self.cfg['hotkey']}"

    def _needs_key(self) -> bool:
        import providers
        p = providers.PRESETS_BY_NAME.get(self.cfg["provider"])
        return bool(p and p.needs_key)

    # ---------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip("PrtSc AI")
        menu = QMenu()
        self.act_snip = QAction(self._snip_text())
        self.act_snip.triggered.connect(self.start_snip)
        self.act_pause = QAction("Pause bubble", checkable=True)
        self.act_pause.toggled.connect(lambda on: self.bubble.hide() if on else None)
        act_settings = QAction("Settings…")
        act_settings.triggered.connect(self.show_settings)
        act_quit = QAction("Quit")
        act_quit.triggered.connect(self.quit)
        for a in (self.act_snip, self.act_pause, act_settings):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._menu, self._actions = menu, (act_settings, act_quit)
        self.tray.setContextMenu(menu)
        if not IS_MAC:  # on macOS a click on the menu-bar icon opens the menu instead
            self.tray.activated.connect(
                lambda r: self.start_snip() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    # ---------------------------------------------------------------- flows
    def _check_clipboard(self) -> None:
        if not self.cfg["bubble_enabled"] or self.act_pause.isChecked():
            return
        md = QGuiApplication.clipboard().mimeData()
        if md is None or not md.hasImage():
            return
        if self.cfg["bubble_snips_only"] and not osys.looks_like_snip():
            return
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return
        self._offer(img)

    @staticmethod
    def _fingerprint(img: QImage) -> bytes:
        small = img.convertToFormat(QImage.Format.Format_RGB32).scaled(32, 32)
        return hashlib.md5(small.bits().asstring(32 * 32 * 4)).digest()

    def _offer(self, img: QImage) -> None:
        """Pop the bubble once per screenshot, whichever way it arrived."""
        if not self.cfg["bubble_enabled"] or self.act_pause.isChecked():
            return
        h = self._fingerprint(img)
        now = time.monotonic()
        if h == self._last_hash and now - self._last_time < 5:
            return  # same image announced twice (snip tool rewrite, file + clipboard)
        self._last_hash, self._last_time = h, now
        self.bubble.popup(img, self.cfg["bubble_timeout"])

    def start_snip(self) -> None:
        self.bubble.hide()
        if IS_MAC and not osys.has_screen_recording():
            osys.request_screen_recording()
            self.show_permission_help()
            return
        QTimer.singleShot(120, self.overlay.start)  # let menus/bubble vanish first

    def show_permission_help(self) -> None:
        from ui import ScreenPermissionDialog
        if self._perm_dialog and self._perm_dialog.isVisible():
            self._perm_dialog.raise_()
            return
        self._perm_dialog = ScreenPermissionDialog()
        if IS_MAC:
            osys.activate_app()
        self._perm_dialog.show()
        self._perm_dialog.raise_()
        self._perm_dialog.activateWindow()

    def open_chat(self, img: QImage) -> None:
        w = ChatWindow(img, self.cfg)
        w.open_settings.connect(self.show_settings)
        w.closed.connect(lambda win: self.chats.remove(win) if win in self.chats else None)
        if self.watcher is not None:
            w.image_saved.connect(self.watcher.ignore)
        self.chats.append(w)
        if IS_MAC:
            osys.activate_app()
        w.show()
        w.raise_()
        w.activateWindow()

    def show_settings(self) -> None:
        if self.settings and self.settings.isVisible():
            self.settings.raise_()
            self.settings.activateWindow()
            return
        self.settings = SettingsDialog(self.cfg)
        self.settings.saved.connect(self._on_saved)
        if IS_MAC:
            osys.activate_app()
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _on_saved(self) -> None:
        self.hotkey.start(self.cfg["hotkey"])
        self.act_snip.setText(self._snip_text())
        if self.watcher is not None:
            self.watcher.only_screenshots = self.cfg["bubble_snips_only"]
            self.watcher.set_folder(osys.screenshot_folder())  # picks up a changed location
        for w in self.chats:
            w.refresh_model_label()

    def quit(self) -> None:
        self.hotkey.stop()
        self.tray.hide()
        self.qapp.quit()


def main() -> int:
    if "--selftest" in sys.argv:  # used by CI against the built exe / .app
        from config import selftest
        rc = selftest()
        if rc == 0 and IS_MAC and osys.parse_hotkey(osys.DEFAULT_HOTKEY) != (0x300, 0x12):
            rc = 2
        if sys.stdout:  # a windowed .exe has no console
            print("selftest", "passed" if rc == 0 else f"FAILED ({rc})")
        return rc
    if "--version" in sys.argv:
        print(__version__)
        return 0
    qapp = QApplication(sys.argv)
    if IS_MAC:
        osys.set_accessory_app()  # menu bar only (the .app also sets LSUIElement)
    qapp.setApplicationName("PrtSc AI")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(app_icon())

    # Single instance. Launching the exe again normally just triggers a snip in the
    # running copy. A NEWER version instead asks the old copy to quit and takes over,
    # so updating is just "download, double-click".
    def vtuple(v: str) -> tuple:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    sock = QLocalSocket()
    sock.connectToServer(SINGLETON)
    if sock.waitForConnected(300):
        sock.write(f"hello:{__version__}".encode())
        sock.waitForBytesWritten(300)
        reply = bytes(sock.readAll()) if sock.waitForReadyRead(800) else b""
        sock.disconnectFromServer()
        if reply != b"quitting":
            return 0  # same/newer copy already running: it handles the snip
        for _ in range(30):  # wait up to ~3s for the old copy to exit
            probe = QLocalSocket()
            probe.connectToServer(SINGLETON)
            if not probe.waitForConnected(100):
                break
            probe.disconnectFromServer()
            time.sleep(0.1)
    QLocalServer.removeServer(SINGLETON)
    server = QLocalServer()
    server.listen(SINGLETON)

    app = App(qapp)

    def on_conn():
        c = server.nextPendingConnection()
        if not c:
            return

        def on_read():
            msg = bytes(c.readAll()).decode(errors="ignore")
            if msg.startswith("hello:") and vtuple(msg[6:]) > vtuple(__version__):
                c.write(b"quitting")
                c.flush()
                c.waitForBytesWritten(300)
                server.close()
                QTimer.singleShot(50, app.quit)
            else:
                c.write(b"ok")
                c.flush()
                app.start_snip()

        c.readyRead.connect(on_read)

    server.newConnection.connect(on_conn)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
