"""All windows: the AI bubble, the snip overlay, the chat window and settings."""
from __future__ import annotations

import sys
import threading
import webbrowser

from PyQt6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QPoint, QRect,
                          QSize, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QIcon, QImage,
                         QKeySequence, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QShortcut)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QSpinBox, QTextBrowser, QVBoxLayout,
                             QWidget)

import providers
from config import Config, set_start_with_windows

IS_MAC = sys.platform == "darwin"
if IS_MAC:
    import macsys as osys
else:
    import winsys as osys

ACCENT = "#7C5CFF"
ACCENT_2 = "#22D3EE"


def _pt(win: float) -> str:
    """Point size that looks the same on both: macOS draws 1pt = 1px, Windows 1pt = 1.33px."""
    return f"{round(win * 1.3) if IS_MAC else win}pt"


def build_style() -> str:
    return f"""
QWidget {{ background: #15161B; color: #E8E8EE; font-family: 'Segoe UI', '.AppleSystemUIFont', 'Helvetica Neue', sans-serif; font-size: {_pt(10)}; }}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTextBrowser {{
    background: #1E2028; border: 1px solid #2E3140; border-radius: 8px; padding: 6px; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QPushButton {{ background: #262938; border: 1px solid #343850; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ background: #30344A; }}
QPushButton:disabled {{ color: #6B6E80; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: #8E72FF; }}
QPushButton#chip {{ background: #1E2028; border-radius: 12px; padding: 3px 10px; font-size: {_pt(9)}; }}
QGroupBox {{ border: 1px solid #2E3140; border-radius: 10px; margin-top: 14px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #A9ABBD; }}
QLabel#muted {{ color: #8C8FA3; font-size: {_pt(9)}; }}
QLabel#error {{ color: #FF7A85; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
"""


STYLE = build_style()


# ------------------------------------------------------------------ helpers

def draw_icon(size: int = 64) -> QPixmap:
    """The app icon, drawn as vectors at any size (64 = tray, 1024 = .icns)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(size / 64, size / 64)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0, QColor(ACCENT))
    g.setColorAt(1, QColor(ACCENT_2))
    path = QPainterPath()
    path.addRoundedRect(2, 2, 60, 60, 16, 16)
    p.fillPath(path, g)
    # dashed snip corners
    p.setPen(QPen(QColor("white"), 4, cap=Qt.PenCapStyle.RoundCap))
    for x, y, dx, dy in ((12, 12, 1, 1), (52, 12, -1, 1), (12, 52, 1, -1), (52, 52, -1, -1)):
        p.drawLine(x, y, x + 9 * dx, y)
        p.drawLine(x, y, x, y + 9 * dy)
    f = QFont("Segoe UI", 15)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "AI")
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon(draw_icon(64))
    icon.addPixmap(draw_icon(128))  # sharp on Retina menu bars / HiDPI trays
    return icon


def image_to_png(img: QImage, max_side: int = 2000, max_bytes: int = 4_500_000) -> bytes:
    """Encode for the API: cap size so every provider accepts it."""
    while True:
        if max(img.width(), img.height()) > max_side:
            img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(ba)
        if len(data) <= max_bytes or max_side < 400:
            return data
        max_side = int(max_side * 0.75)


class _Signals(QObject):
    done = pyqtSignal(object)
    error = pyqtSignal(str)


def run_bg(fn, on_done, on_error):
    """Run fn() off the UI thread, deliver result back on it."""
    s = _Signals()
    s.done.connect(on_done)
    s.error.connect(on_error)

    def work():
        try:
            s.done.emit(fn())
        except Exception as e:  # noqa: BLE001
            s.error.emit(str(e))

    threading.Thread(target=work, daemon=True).start()
    return s  # caller keeps a reference so signals live


# ------------------------------------------------------------------ bubble

class Bubble(QWidget):
    """Small pill that appears next to the cursor after a Windows snip / macOS screenshot."""
    ask = pyqtSignal(QImage)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.image = QImage()
        self._timeout_ms = 3000
        self._elapsed = 0

        card = QFrame(self)
        card.setObjectName("card")
        card.setStyleSheet(f"""
            QFrame#card {{ background: #15161B; border: 1px solid #343850; border-radius: 14px; }}
            QLabel {{ background: transparent; }}
            QPushButton#ai {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {ACCENT}, stop:1 {ACCENT_2});
                              color: white; border: none; border-radius: 10px; padding: 7px 16px;
                              font-weight: 700; font-size: {_pt(11)}; }}
            QPushButton#ai:hover {{ background: {ACCENT}; }}
            QPushButton#x {{ background: transparent; border: none; color: #8C8FA3; font-size: {_pt(12)}; padding: 2px 6px; }}
            QPushButton#x:hover {{ color: white; }}
            QProgressBar {{ background: #262938; border: none; border-radius: 1px; max-height: 3px; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 1px; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 8)
        lay.setSpacing(6)
        row = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(56, 40)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn = QPushButton("✦  AI")
        self.btn.setObjectName("ai")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._on_ask)
        close = QPushButton("✕")
        close.setObjectName("x")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Dismiss")
        close.clicked.connect(self.hide)
        row.addWidget(self.thumb)
        row.addWidget(self.btn)
        row.addWidget(close)
        lay.addLayout(row)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

    def popup(self, image: QImage, timeout_s: int) -> None:
        self.image = image
        thumb = QPixmap.fromImage(image).scaled(56, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
        self.thumb.setPixmap(thumb)
        self._timeout_ms = max(1, min(10, timeout_s)) * 1000
        self._elapsed = 0
        self.bar.setValue(1000)
        self.adjustSize()
        # place near the cursor (where the snip just ended), kept on-screen
        pos = QCursor.pos()
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = scr.availableGeometry()
        x = min(max(pos.x() + 16, area.left() + 8), area.right() - self.width() - 8)
        y = min(max(pos.y() + 16, area.top() + 8), area.bottom() - self.height() - 8)
        self.move(x, y)
        self.show()
        self.raise_()
        self.timer.start()

    def _tick(self) -> None:
        if self.underMouse():  # hovering pauses the countdown
            return
        self._elapsed += self.timer.interval()
        left = max(0, self._timeout_ms - self._elapsed)
        self.bar.setValue(int(1000 * left / self._timeout_ms))
        if left == 0:
            self.hide()

    def _on_ask(self) -> None:
        self.hide()
        self.ask.emit(self.image)

    def hideEvent(self, e) -> None:
        self.timer.stop()
        super().hideEvent(e)


# ------------------------------------------------------------------ snip overlay

class _ScreenOverlay(QWidget):
    selected = pyqtSignal(QImage)
    cancelled = pyqtSignal()

    def __init__(self, screen, shot: QPixmap) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.shot = shot
        self.origin: QPoint | None = None
        self.sel = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if not self.sel.isNull():
            r = self.sel.normalized()
            p.drawPixmap(r, self.shot, self._phys(r))
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRect(r.adjusted(0, 0, -1, -1))
            label = f"{r.width()} × {r.height()}"
            p.setFont(QFont("Segoe UI", 12 if IS_MAC else 9))
            tw = p.fontMetrics().horizontalAdvance(label) + 12
            ty = r.top() - 24 if r.top() > 30 else r.bottom() + 6
            p.fillRect(QRect(r.left(), ty, tw, 20), QColor(ACCENT))
            p.setPen(QColor("white"))
            p.drawText(QRect(r.left(), ty, tw, 20), Qt.AlignmentFlag.AlignCenter, label)
        else:
            p.setPen(QColor("white"))
            p.setFont(QFont("Segoe UI", 16 if IS_MAC else 12))
            p.drawText(self.rect().adjusted(0, 40, 0, 0),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "Drag to select an area for AI  •  Esc to cancel")

    def _phys(self, r: QRect) -> QRect:
        # Pixels per logical point, measured rather than trusted: Retina (2x),
        # mixed-DPI multi-monitor setups and Windows scaling all come out right.
        w = max(1, self.width())
        d = self.shot.width() / w if self.shot.width() else self.shot.devicePixelRatio()
        return QRect(round(r.x() * d), round(r.y() * d), round(r.width() * d), round(r.height() * d))

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        self.origin = e.position().toPoint()
        self.sel = QRect(self.origin, self.origin)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if self.origin is not None:
            self.sel = QRect(self.origin, e.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self.origin is None:
            return
        r = self.sel.normalized()
        self.origin = None
        if r.width() < 6 or r.height() < 6:  # a click, not a drag
            self.sel = QRect()
            self.update()
            return
        self.selected.emit(self.shot.copy(self._phys(r)).toImage())

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class SnipOverlay(QObject):
    """One overlay per monitor; first finished selection wins."""
    captured = pyqtSignal(QImage)

    def __init__(self) -> None:
        super().__init__()
        self.windows: list[_ScreenOverlay] = []

    def start(self) -> None:
        if self.windows:
            return
        shots = [(s, s.grabWindow(0)) for s in QGuiApplication.screens()]  # grab BEFORE showing
        for screen, shot in shots:
            w = _ScreenOverlay(screen, shot)
            w.selected.connect(self._done)
            w.cancelled.connect(self._close)
            self.windows.append(w)
            if IS_MAC:
                # Full screen would slide into a new Space; cover the display instead,
                # above the menu bar and the Dock.
                w.setGeometry(screen.geometry())
                w.show()
                osys.float_above_everything(w)
            else:
                w.showFullScreen()
        if IS_MAC:
            osys.activate_app()
        under = QGuiApplication.screenAt(QCursor.pos())
        for w in self.windows:
            if w.screen() == under:
                w.activateWindow()
                w.raise_()
                w.setFocus()

    def _done(self, img: QImage) -> None:
        self._close()
        self.captured.emit(img)

    def _close(self) -> None:
        for w in self.windows:
            w.close()
            w.deleteLater()
        self.windows = []


# ------------------------------------------------------------------ chat window

QUICK_PROMPTS = ["Explain this", "Extract the text", "Translate to English",
                 "Summarize", "Solve / answer this", "What's wrong here?"]


class ChatWindow(QWidget):
    open_settings = pyqtSignal()
    retrying = pyqtSignal(int, int, int)
    closed = pyqtSignal(object)
    image_saved = pyqtSignal(str)

    def __init__(self, image: QImage, cfg: Config) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.cfg = cfg
        self.image = image
        self.png = image_to_png(image)
        self.history: list[dict] = []
        self._pending = None
        self.setWindowTitle("PrtSc AI")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(STYLE)
        self.resize(560, 680)
        self.retrying.connect(self._on_retrying)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.model_label = QLabel()
        self.model_label.setObjectName("muted")
        self.pin = QPushButton("📌")
        self.pin.setCheckable(True)
        self.pin.setToolTip("Keep on top")
        self.pin.toggled.connect(self._toggle_pin)
        gear = QPushButton("⚙")
        gear.setToolTip("Settings")
        gear.clicked.connect(self.open_settings.emit)
        top.addWidget(self.model_label, 1)
        top.addWidget(self.pin)
        top.addWidget(gear)
        root.addLayout(top)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #0E0F13; border: 1px solid #2E3140; border-radius: 10px;")
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(
            520, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.preview.setMinimumHeight(80)
        self.preview.setMaximumHeight(212)
        root.addWidget(self.preview)

        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(True)
        self.log.setPlaceholderText("Ask anything about your snip…")
        root.addWidget(self.log, 1)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chip_widgets = []
        for q in QUICK_PROMPTS[:4]:
            b = QPushButton(q)
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=q: self.send(t))
            chips.addWidget(b)
            self.chip_widgets.append(b)
        chips.addStretch()
        root.addLayout(chips)

        row = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Ask about this snip…  (Enter to send, Shift+Enter for new line)")
        self.input.setFixedHeight(64)
        self.input.installEventFilter(self)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.setFixedHeight(64)
        self.send_btn.clicked.connect(lambda: self.send(self.input.toPlainText()))
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        root.addLayout(row)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("muted")
        copy_btn = QPushButton("Copy answer")
        copy_btn.clicked.connect(self._copy_last)
        save_btn = QPushButton("Save image")
        save_btn.clicked.connect(self._save_image)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(save_btn)
        bottom.addWidget(copy_btn)
        root.addLayout(bottom)

        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        self.refresh_model_label()
        self.input.setFocus()

    # --- UI bits
    def refresh_model_label(self) -> None:
        prov = self.cfg["provider"]
        model = self.cfg.provider_field(prov, "model") or "no model set"
        self.model_label.setText(f"{prov}  ·  {model}")

    def _toggle_pin(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.input and ev.type() == ev.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                    not ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.send(self.input.toPlainText())
                return True
        return super().eventFilter(obj, ev)

    def _render(self, thinking: bool = False) -> None:
        parts = []
        for m in self.history:
            who = "**You**" if m["role"] == "user" else "**AI**"
            parts.append(f"{who}\n\n{m['text']}")
        if thinking:
            parts.append("**AI**\n\n_thinking…_")
        self.log.setMarkdown("\n\n---\n\n".join(parts))
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _busy(self, on: bool) -> None:
        self.send_btn.setEnabled(not on)
        for c in self.chip_widgets:
            c.setEnabled(not on)
        self.status.setText("Thinking…" if on else "")

    # --- sending
    def send(self, text: str) -> None:
        text = text.strip()
        if not text or not self.send_btn.isEnabled():
            return
        prov_name = self.cfg["provider"]
        preset = providers.PRESETS_BY_NAME.get(prov_name)
        if preset is None:
            self.status.setText("Unknown provider. Open Settings.")
            return
        base = self.cfg.provider_field(prov_name, "base_url", preset.base_url)
        model = self.cfg.provider_field(prov_name, "model")
        key = Config.get_key(prov_name)
        if preset.needs_key and not key:
            self.status.setText("No API key yet — opening Settings.")
            self.open_settings.emit()
            return

        first = not self.history
        self.history.append({"role": "user", "text": text, "image": self.png if first else None})
        self.input.clear()
        self._render(thinking=True)
        self._busy(True)
        snapshot = list(self.history)
        self._pending = run_bg(
            lambda: providers.chat(preset.kind, base, key, model, snapshot, provider=prov_name.split(' (')[0],
                                   on_retry=lambda n, total, wait: self.retrying.emit(n, total, wait)),
            self._on_reply, self._on_error)

    def _on_retrying(self, n: int, total: int, wait: int) -> None:
        self.status.setText(f"Server busy, retrying in {wait}s (attempt {n}/{total})…")

    def _on_reply(self, text: str) -> None:
        self.history.append({"role": "assistant", "text": text or "_(empty reply)_", "image": None})
        self._render()
        self._busy(False)
        self.input.setFocus()

    def _on_error(self, msg: str) -> None:
        # drop the failed user turn so the user can retry cleanly
        failed = self.history.pop() if self.history and self.history[-1]["role"] == "user" else None
        self._render()
        self._busy(False)
        if failed:
            self.input.setPlainText(failed["text"])
        self.status.setText("Couldn't get an answer. Your question is back in the box, press Send to retry.")
        QMessageBox.warning(self, "PrtSc AI", msg)

    def _copy_last(self) -> None:
        for m in reversed(self.history):
            if m["role"] == "assistant":
                QApplication.clipboard().setText(m["text"])
                self.status.setText("Copied.")
                return

    def _save_image(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Save snip", "snip.png", "PNG (*.png)")
        if path:
            self.image_saved.emit(path)  # so the screenshot-folder watcher ignores it
            self.image.save(path, "PNG")

    def closeEvent(self, e) -> None:
        self.closed.emit(self)
        super().closeEvent(e)


# ------------------------------------------------------------------ settings

class SettingsDialog(QDialog):
    saved = pyqtSignal()

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._jobs = []
        self.setWindowTitle("PrtSc AI — Settings")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(600 if IS_MAC else 520)

        root = QVBoxLayout(self)

        # --- AI provider
        box = QGroupBox("AI provider")
        form = QFormLayout(box)
        self.provider = QComboBox()
        self.provider.addItems([p.name for p in providers.PRESETS])
        self.base_url = QLineEdit()
        key_row = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste API key")
        show = QPushButton("👁")
        show.setCheckable(True)
        show.setFixedWidth(36)
        show.toggled.connect(lambda on: self.key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.get_key = QPushButton("Get a key ↗")
        self.get_key.clicked.connect(self._open_key_page)
        key_row.addWidget(self.key, 1)
        key_row.addWidget(show)
        key_row.addWidget(self.get_key)
        model_row = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("Type a model name or fetch the list")
        self.fetch = QPushButton("Fetch models")
        self.fetch.clicked.connect(self._fetch_models)
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.fetch)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test with an image")
        self.test_btn.clicked.connect(self._test)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)

        form.addRow("Provider", self.provider)
        form.addRow("Base URL", self.base_url)
        form.addRow("API key", key_row)
        form.addRow("Model", model_row)
        form.addRow("", self.hint)
        form.addRow("", test_row)
        root.addWidget(box)

        # --- behaviour
        box2 = QGroupBox("Behaviour")
        f2 = QFormLayout(box2)
        if IS_MAC:
            self.bubble = QCheckBox("Show the AI bubble after ⇧⌘3 / ⇧⌘4 / ⇧⌘5 screenshots")
            self.snips_only = QCheckBox("Only for screenshots")
            # explicit line breaks: word-wrapped labels get clipped in form layouts
            self.hotkey_hint = QLabel("Other images saved to the screenshot folder are ignored.\n"
                                      "Copied images (⌃⇧⌘4) always show it: macOS doesn't\n"
                                      "say which app copied them.")
            self.hotkey_hint.setObjectName("muted")
            self.autostart = QCheckBox("Open PrtSc AI at login")
            hk_example = "e.g. Cmd+Shift+1"
        else:
            self.bubble = QCheckBox("Show the AI bubble after Win+Shift+S / PrtSc snips")
            self.snips_only = QCheckBox("Only for Windows snips (ignore images copied from other apps)")
            self.hotkey_hint = None
            self.autostart = QCheckBox("Start PrtSc AI when Windows starts")
            hk_example = "e.g. Win+Shift+A"
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 10)
        self.timeout.setSuffix(" s")
        self.hotkey = QLineEdit()
        self.hotkey.setPlaceholderText(hk_example)
        hk_row = QHBoxLayout()
        hk_row.addWidget(self.hotkey, 1)
        self.hotkey_preview = QLabel()
        self.hotkey_preview.setObjectName("hkcap")
        self.hotkey_preview.setStyleSheet(
            "QLabel#hkcap { background: #262938; border: 1px solid #343850; border-radius: 6px;"
            f" padding: 3px 8px; font-weight: 600; font-size: {_pt(10)}; }}")
        self.hotkey_preview.setVisible(IS_MAC)
        hk_row.addWidget(self.hotkey_preview)
        self.hotkey.textChanged.connect(self._update_hotkey_preview)
        f2.addRow(self.bubble)
        f2.addRow("Bubble disappears after", self.timeout)
        f2.addRow(self.snips_only)
        if self.hotkey_hint is not None:
            self.hotkey_hint.setContentsMargins(26, 0, 0, 4)
            f2.addRow(self.hotkey_hint)
        f2.addRow("Direct AI snip hotkey", hk_row)
        f2.addRow(self.autostart)
        root.addWidget(box2)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

        # load values
        self._drafts: dict[str, dict] = {}
        self._current = cfg["provider"]
        self.provider.setCurrentText(self._current)
        self._load_provider(self._current)
        self.provider.currentTextChanged.connect(self._switch_provider)
        self.bubble.setChecked(cfg["bubble_enabled"])
        self.timeout.setValue(cfg["bubble_timeout"])
        self.snips_only.setChecked(cfg["bubble_snips_only"])
        self.hotkey.setText(cfg["hotkey"])
        self.autostart.setChecked(cfg["start_with_windows"])
        self.bubble.toggled.connect(self.timeout.setEnabled)
        self.timeout.setEnabled(self.bubble.isChecked())

    def _update_hotkey_preview(self, text: str) -> None:
        ok = osys.parse_hotkey(text.strip()) is not None
        self.hotkey_preview.setText(osys.hotkey_label(text.strip()) if ok else "?")

    # --- provider switching keeps unsaved edits per provider
    def _preset(self) -> providers.Preset:
        return providers.PRESETS_BY_NAME[self.provider.currentText()]

    def _stash(self) -> None:
        self._drafts[self._current] = {"base_url": self.base_url.text().strip(),
                                       "key": self.key.text().strip(),
                                       "model": self.model.currentText().strip()}

    def _load_provider(self, name: str) -> None:
        p = providers.PRESETS_BY_NAME[name]
        d = self._drafts.get(name)
        self.base_url.setText(d["base_url"] if d else self.cfg.provider_field(name, "base_url", p.base_url))
        self.base_url.setReadOnly(not name.startswith("Custom") and "Ollama" not in name)
        saved = Config.get_key(name)
        self.key.setText(d["key"] if d else saved)
        if saved and not d:
            self.test_result.setStyleSheet("color: #4ADE80;")
        self.key.setPlaceholderText("Paste API key" if p.needs_key else "Optional")
        self.model.clear()
        self.model.setEditText(d["model"] if d else self.cfg.provider_field(name, "model"))
        self.get_key.setVisible(bool(p.key_url))
        self.hint.setText(p.hint or "Pick a model that accepts images (vision).")
        store = "your Keychain" if IS_MAC else "Windows"
        self.test_result.setText(f"✓ Saved key loaded from {store}. No need to paste it again."
                                 if saved and not d else "")
        if not (saved and not d):
            self.test_result.setStyleSheet("")

    def _switch_provider(self, name: str) -> None:
        self._stash()
        self._current = name
        self._load_provider(name)

    def _open_key_page(self) -> None:
        if self._preset().key_url:
            webbrowser.open(self._preset().key_url)

    # --- network actions
    def _fetch_models(self) -> None:
        p, base, key = self._preset(), self.base_url.text().strip(), self.key.text().strip()
        self.fetch.setEnabled(False)
        self.fetch.setText("Fetching…")

        def ok(ids):
            cur = self.model.currentText()
            self.model.clear()
            self.model.addItems(ids)
            self.model.setEditText(cur)
            self.fetch.setEnabled(True)
            self.fetch.setText("Fetch models")
            self.model.showPopup()

        def err(msg):
            self.fetch.setEnabled(True)
            self.fetch.setText("Fetch models")
            QMessageBox.warning(self, "Fetch models", msg)

        self._jobs.append(run_bg(lambda: providers.list_models(p.kind, base, key), ok, err))

    def _test(self) -> None:
        p, base = self._preset(), self.base_url.text().strip()
        key, model = self.key.text().strip(), self.model.currentText().strip()
        img = QImage(64, 64, QImage.Format.Format_RGB32)
        img.fill(QColor(220, 30, 30))
        hist = [{"role": "user", "image": image_to_png(img),
                 "text": "What colour is this image? Answer with one word."}]
        self.test_btn.setEnabled(False)
        self.test_result.setObjectName("muted")
        self.test_result.setText("Testing…")

        def ok(reply):
            self.test_btn.setEnabled(True)
            good = "red" in reply.lower()
            self.test_result.setObjectName("" if good else "error")
            self.test_result.setStyleSheet("color: #4ADE80;" if good else "")
            self.test_result.setText("✓ Works, and it can see images." if good
                                     else f"Replied “{reply[:60]}” — may not support images.")

        def err(msg):
            self.test_btn.setEnabled(True)
            self.test_result.setStyleSheet("color: #FF7A85;")
            self.test_result.setText(msg[:300])

        self._jobs.append(run_bg(lambda: providers.chat(p.kind, base, key, model, hist), ok, err))

    # --- save
    def _save(self) -> None:
        hk = self.hotkey.text().strip()
        if hk and osys.parse_hotkey(hk) is None:
            QMessageBox.warning(self, "Hotkey", "Use a format like Cmd+Shift+1 or Ctrl+Option+Q."
                                if IS_MAC else "Use a format like Win+Shift+A or Ctrl+Alt+Q.")
            return
        self._stash()
        failed = []
        for name, d in self._drafts.items():
            self.cfg.set_provider_field(name, "base_url", d["base_url"])
            self.cfg.set_provider_field(name, "model", d["model"])
            if d["key"] != Config.get_key(name) and not Config.set_key(name, d["key"]):
                failed.append(name)
        if failed:
            QMessageBox.warning(self, "API key", "Couldn't save the key for " + ", ".join(failed) +
                                (" to your Keychain." if IS_MAC else " to Windows.") +
                                " It will work until you quit PrtSc AI.")
        self.cfg["provider"] = self._current
        self.cfg["bubble_enabled"] = self.bubble.isChecked()
        self.cfg["bubble_timeout"] = self.timeout.value()
        self.cfg["bubble_snips_only"] = self.snips_only.isChecked()
        self.cfg["hotkey"] = hk or osys.DEFAULT_HOTKEY
        self.cfg["start_with_windows"] = self.autostart.isChecked()
        self.cfg["first_run"] = False
        self.cfg.save()
        try:
            set_start_with_windows(self.cfg["start_with_windows"])
        except Exception:
            pass
        self.saved.emit()
        self.accept()


# ------------------------------------------------------------------ macOS permission

class ScreenPermissionDialog(QDialog):
    """Explains macOS's Screen Recording permission, with a button to the right pane."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PrtSc AI — Screen Recording")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        root.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(draw_icon(112).scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        icon.setFixedSize(56, 56)
        title = QLabel("Allow Screen Recording")
        title.setStyleSheet(f"font-size: {_pt(14)}; font-weight: 700;")
        sub = QLabel("PrtSc AI needs it to see the part\nof the screen you snip.")
        sub.setObjectName("muted")
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        tcol.addWidget(title)
        tcol.addWidget(sub)
        head.addWidget(icon)
        head.addLayout(tcol, 1)
        root.addLayout(head)

        steps = QLabel(
            "1.&nbsp; Click <b>Open System Settings</b>.<br>"
            "2.&nbsp; Go to <b>Privacy &amp; Security → Screen Recording</b><br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;and turn on <b>PrtSc AI</b>.<br>"
            "3.&nbsp; If macOS asks, choose <b>Quit &amp; Reopen</b>.")
        steps.setTextFormat(Qt.TextFormat.RichText)
        steps.setStyleSheet("background: #1E2028; border: 1px solid #2E3140; border-radius: 10px;"
                            " padding: 10px 12px;")
        root.addWidget(steps)
        note = QLabel("Your screen is only read when you snip. Images go only to the\n"
                      "AI provider you picked, and only when you press Send.")
        note.setObjectName("muted")
        root.addWidget(note)

        btns = QHBoxLayout()
        btns.addStretch()
        later = QPushButton("Later")
        later.clicked.connect(self.reject)
        go = QPushButton("Open System Settings")
        go.setObjectName("primary")
        go.setDefault(True)
        go.clicked.connect(self._open)
        btns.addWidget(later)
        btns.addWidget(go)
        root.addLayout(btns)

    def _open(self) -> None:
        try:
            osys.open_privacy_pane()
        except Exception:
            pass
        self.accept()
