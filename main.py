"""PrtSc AI — Circle-to-Search for Windows.

* Win+Shift+S / PrtSc snip  -> "AI" bubble pops next to the cursor (timeout 1-10 s)
* Win+Shift+A               -> straight to an AI snip, no bubble
* Tray icon                 -> snip, settings, pause bubble, quit
"""
from __future__ import annotations

import hashlib
import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QGuiApplication, QImage
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import winsys
from config import Config, set_start_with_windows
from ui import Bubble, ChatWindow, SettingsDialog, SnipOverlay, app_icon

__version__ = "1.0.2"
SINGLETON = "PrtSc-AI-singleton"


class App:
    def __init__(self, qapp: QApplication) -> None:
        self.qapp = qapp
        self.cfg = Config()
        self.chats: list[ChatWindow] = []
        self.settings: SettingsDialog | None = None
        self._last_hash = b""
        self._last_time = 0.0

        self.bubble = Bubble()
        self.bubble.ask.connect(self.open_chat)
        self.overlay = SnipOverlay()
        self.overlay.captured.connect(self.open_chat)

        # clipboard watcher (debounced — the snip tool can write more than once)
        self._debounce = QTimer(singleShot=True, interval=150)
        self._debounce.timeout.connect(self._check_clipboard)
        QGuiApplication.clipboard().dataChanged.connect(self._debounce.start)

        # global hotkey
        self.hotkey = winsys.GlobalHotkey()
        self.hotkey.triggered.connect(self.start_snip)
        self.hotkey.failed.connect(lambda m: self.tray.showMessage("PrtSc AI", m))

        self._build_tray()
        self.hotkey.start(self.cfg["hotkey"])

        # Always point "start with Windows" at THIS exe, so a newer download takes over.
        try:
            set_start_with_windows(self.cfg["start_with_windows"])
        except Exception:
            pass

        prev = self.cfg.data.get("last_version")
        has_key = bool(Config.get_key(self.cfg["provider"])) or not self._needs_key()
        if prev and prev != __version__:
            self.tray.showMessage(
                f"PrtSc AI updated to v{__version__}",
                "Your settings and API keys were carried over from your previous version.")
        elif self.cfg["first_run"] and not has_key:
            self.tray.showMessage(
                "PrtSc AI is running",
                f"Snip with Win+Shift+S and click the AI bubble, or press {self.cfg['hotkey']}.")
        if not has_key:
            QTimer.singleShot(400, self.show_settings)
        else:
            self.cfg["first_run"] = False
        self.cfg["last_version"] = __version__
        try:
            self.cfg.save()
        except Exception:
            pass

    def _needs_key(self) -> bool:
        import providers
        p = providers.PRESETS_BY_NAME.get(self.cfg["provider"])
        return bool(p and p.needs_key)

    # ---------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon())
        self.tray.setToolTip("PrtSc AI")
        menu = QMenu()
        self.act_snip = QAction(f"Snip with AI\t{self.cfg['hotkey']}")
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
        if self.cfg["bubble_snips_only"] and not winsys.looks_like_snip():
            return
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return
        h = hashlib.md5(img.scaled(32, 32).bits().asstring(32 * 32 * 4)).digest()
        now = time.monotonic()
        if h == self._last_hash and now - self._last_time < 3:
            return  # same snip announced twice
        self._last_hash, self._last_time = h, now
        self.bubble.popup(img, self.cfg["bubble_timeout"])

    def start_snip(self) -> None:
        self.bubble.hide()
        QTimer.singleShot(120, self.overlay.start)  # let menus/bubble vanish first

    def open_chat(self, img: QImage) -> None:
        w = ChatWindow(img, self.cfg)
        w.open_settings.connect(self.show_settings)
        w.closed.connect(lambda win: self.chats.remove(win) if win in self.chats else None)
        self.chats.append(w)
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
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _on_saved(self) -> None:
        self.hotkey.start(self.cfg["hotkey"])
        self.act_snip.setText(f"Snip with AI\t{self.cfg['hotkey']}")
        for w in self.chats:
            w.refresh_model_label()

    def quit(self) -> None:
        self.hotkey.stop()
        self.tray.hide()
        self.qapp.quit()


def main() -> int:
    if "--selftest" in sys.argv:  # used by CI against the built exe
        from config import selftest
        return selftest()
    if "--version" in sys.argv:
        print(__version__)
        return 0
    qapp = QApplication(sys.argv)
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
