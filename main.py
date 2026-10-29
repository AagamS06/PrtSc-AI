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

        if self.cfg["first_run"]:
            try:
                set_start_with_windows(self.cfg["start_with_windows"])
            except Exception:
                pass
            self.tray.showMessage(
                "PrtSc AI is running",
                f"Snip with Win+Shift+S and click the AI bubble, or press {self.cfg['hotkey']}.")
            QTimer.singleShot(400, self.show_settings)

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
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("PrtSc AI")
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(app_icon())

    # single instance: a second launch just triggers a snip in the first one
    sock = QLocalSocket()
    sock.connectToServer(SINGLETON)
    if sock.waitForConnected(300):
        sock.write(b"snip")
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SINGLETON)
    server = QLocalServer()
    server.listen(SINGLETON)

    app = App(qapp)

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(lambda: (c.readAll(), app.start_snip()))

    server.newConnection.connect(on_conn)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
