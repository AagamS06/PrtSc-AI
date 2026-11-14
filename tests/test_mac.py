"""macOS logic that can run anywhere (offscreen Qt): hotkey parsing/labels,
the screenshot-folder watcher, and the LaunchAgent writer.
Run: QT_QPA_PLATFORM=offscreen python tests/test_mac.py"""
import os
import plistlib
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import macsys  # noqa: E402


def spin(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # --- hotkeys
    P = macsys.parse_hotkey
    assert P("Cmd+Shift+1") == (0x300, 0x12)
    assert P("Command+Shift+1") == P("cmd + shift + 1") == P("⇧⌘1") == (0x300, 0x12)
    assert P("Ctrl+Option+Q") == (0x1800, 0x0C)
    assert P("Cmd+F5") == (0x100, 0x60)
    assert P("1") is None and P("Cmd+Shift") is None and P("Cmd+Shift+Nope") is None
    assert macsys.hotkey_label("Cmd+Shift+1") == "⇧⌘1"
    assert macsys.hotkey_label("shift+ctrl+cmd+4") == "⌃⇧⌘4"
    assert macsys.hotkey_label("Option+Cmd+Space") == "⌥⌘Space"
    assert macsys.looks_like_snip() is True

    # --- screenshot folder watcher
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        img = QImage(120, 80, QImage.Format.Format_RGB32)
        img.fill(QColor("#7C5CFF"))
        img.save(str(d / "Screenshot old.png"))  # existed before: ignored
        w = macsys.ScreenshotWatcher(d, only_screenshots=True)
        got = []
        w.captured.connect(lambda im, p: got.append((im.size().width(), Path(p).name)))
        time.sleep(1.1)
        img.save(str(d / ".Screenshot 2026-11-14 at 10.00.00.png"))   # temp name: ignored
        os.replace(d / ".Screenshot 2026-11-14 at 10.00.00.png", d / "Screenshot 2026-11-14 at 10.00.00.png")
        img.save(str(d / "holiday.png"))                          # not a screenshot
        (d / "notes.txt").write_text("hi")                        # not an image
        w.ignore(str(d / "Screenshot saved-by-us.png"))
        img.save(str(d / "Screenshot saved-by-us.png"))           # our own "Save image"
        for _ in range(30):
            spin(100)
            w._scan()  # QFileSystemWatcher can be slow on CI file systems
        assert got == [(120, "Screenshot 2026-11-14 at 10.00.00.png")], got
        # a second change of the same file must not announce it again
        img.save(str(d / "Screenshot 2026-11-14 at 10.00.00.png"))
        for _ in range(5):
            spin(100)
            w._scan()
        assert len(got) == 1, got
        # with the filter off, any new image counts
        w.only_screenshots = False
        img.save(str(d / "holiday2.png"))
        for _ in range(10):
            spin(100)
            w._scan()
        assert [g[1] for g in got] == ["Screenshot 2026-11-14 at 10.00.00.png", "holiday2.png"], got

    # --- open at login (LaunchAgent)
    with tempfile.TemporaryDirectory() as d:
        agent = Path(d) / "LaunchAgents" / "com.aagams06.prtscai.plist"
        assert macsys.set_open_at_login(True, agent)
        pl = plistlib.loads(agent.read_bytes())
        assert pl["Label"] == "com.aagams06.prtscai" and pl["RunAtLoad"] is True
        assert pl["ProgramArguments"][-1].endswith("main.py")
        assert macsys.set_open_at_login(True, agent)  # unchanged rewrite is fine
        sys.frozen, exe = True, sys.executable
        try:
            sys.executable = "/Volumes/PrtSc AI/PrtSc AI.app/Contents/MacOS/PrtSc AI"
            assert macsys.set_open_at_login(True, agent) is False  # never point at the .dmg
            assert plistlib.loads(agent.read_bytes())["ProgramArguments"][-1].endswith("main.py")
        finally:
            del sys.frozen
            sys.executable = exe
        assert macsys.set_open_at_login(False, agent) and not agent.exists()

    print("mac logic tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
