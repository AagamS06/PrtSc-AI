"""Run on a real macOS session (CI's macOS runners have one): exercises the
system calls that the Linux tests can only stub. Exit code 0 = all good."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

import macsys  # noqa: E402


def main() -> int:
    assert macsys.IS_MAC, "run this on macOS"
    app = QApplication(sys.argv)
    macsys.set_accessory_app()
    hk = macsys.GlobalHotkey()
    errors = []
    hk.failed.connect(errors.append)
    ok = hk.start("Cmd+Shift+1")
    print("Carbon hotkey registered:", ok, errors)
    assert ok and not errors, errors
    assert hk.start("Ctrl+Option+F9"), "re-registering a different hotkey failed"
    hk.stop()
    print("Screen Recording granted (CI: usually False):", macsys.has_screen_recording())
    print("Screenshot folder:", macsys.screenshot_folder())
    w = QWidget()
    w.resize(200, 100)
    w.show()
    macsys.float_above_everything(w)  # must not crash
    macsys.activate_app()
    shots = [s.grabWindow(0) for s in app.screens()]
    print("screens:", [(s.geometry().getRect(), s.devicePixelRatio()) for s in app.screens()],
          "grabs:", [(p.width(), p.height(), p.devicePixelRatio()) for p in shots])
    QTimer.singleShot(300, app.quit)
    app.exec()
    print("native mac checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
