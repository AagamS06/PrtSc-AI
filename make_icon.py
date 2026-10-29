"""Draw the app icon to assets/icon.ico (run by build.bat)."""
import os
import sys

from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from ui import app_icon  # noqa: E402

os.makedirs("assets", exist_ok=True)
app_icon().pixmap(256, 256).save("assets/icon.png")
from PIL import Image  # noqa: E402

Image.open("assets/icon.png").save(
    "assets/icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written")
