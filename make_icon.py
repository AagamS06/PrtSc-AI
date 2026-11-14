"""Draw the app icon: assets/icon.png + icon.ico (Windows) + icon.icns (macOS).
Run by build.bat / build.sh and CI."""
import os
import sys

from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)
from ui import draw_icon  # noqa: E402

os.makedirs("assets", exist_ok=True)
draw_icon(1024).save("assets/icon-1024.png")
draw_icon(256).save("assets/icon.png")
from PIL import Image  # noqa: E402

Image.open("assets/icon.png").save(
    "assets/icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
# Pillow writes .icns on any OS; the 1024 source gives it every Retina size.
Image.open("assets/icon-1024.png").save("assets/icon.icns")
print("icon written")
