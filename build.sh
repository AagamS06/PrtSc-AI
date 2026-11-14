#!/bin/bash
# Build "PrtSc AI.app" and PrtSc-AI-mac.dmg in dist/ on macOS. Needs Python 3.10+.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt pyinstaller pillow
QT_QPA_PLATFORM=offscreen .venv/bin/python make_icon.py
.venv/bin/pyinstaller --noconfirm --windowed --name "PrtSc AI" --icon assets/icon.icns \
  --osx-bundle-identifier com.aagams06.prtscai \
  --hidden-import keyring.backends.macOS --hidden-import keyring.backends.macOS.api main.py
APP="dist/PrtSc AI.app"
PL="$APP/Contents/Info.plist"
VERSION=$(.venv/bin/python main.py --version)
plutil -replace LSUIElement -bool true "$PL"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PL"
plutil -replace CFBundleVersion -string "$VERSION" "$PL"
plutil -replace NSHighResolutionCapable -bool true "$PL"
plutil -replace NSScreenCaptureUsageDescription -string "PrtSc AI reads the part of the screen you snip so it can send it to the AI you choose." "$PL"
plutil -replace NSDesktopFolderUsageDescription -string "PrtSc AI watches your screenshot folder so it can offer the AI bubble after you take a screenshot." "$PL"
plutil -replace NSDocumentsFolderUsageDescription -string "PrtSc AI watches your screenshot folder so it can offer the AI bubble after you take a screenshot." "$PL"
plutil -replace NSDownloadsFolderUsageDescription -string "PrtSc AI watches your screenshot folder so it can offer the AI bubble after you take a screenshot." "$PL"
codesign --force --deep -s - "$APP"
"$APP/Contents/MacOS/PrtSc AI" --selftest
rm -rf dist/dmg && mkdir dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "PrtSc AI" -srcfolder dist/dmg -ov -format UDZO dist/PrtSc-AI-mac.dmg
rm -rf dist/dmg
echo
echo "Done: $APP and dist/PrtSc-AI-mac.dmg"
