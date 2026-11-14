# PrtSc AI

**Circle to Search, for Windows and Mac.** Snip any part of your screen and ask AI about it — Claude, ChatGPT, Gemini, Grok, DeepSeek, OpenRouter, Ollama or any OpenAI-compatible API.

| Platform | Download |
|---|---|
| **Windows 10/11** | [⬇ PrtSc-AI.exe](https://github.com/AagamS06/PrtSc-AI/releases/latest/download/PrtSc-AI.exe) |
| **Mac — Apple Silicon** (M1/M2/M3/M4…) | [⬇ PrtSc-AI-mac-arm64.dmg](https://github.com/AagamS06/PrtSc-AI/releases/latest/download/PrtSc-AI-mac-arm64.dmg) |
| **Mac — Intel** | [⬇ PrtSc-AI-mac-intel.dmg](https://github.com/AagamS06/PrtSc-AI/releases/latest/download/PrtSc-AI-mac-intel.dmg) |
| Linux | Coming soon. |

Not sure which Mac you have? Apple menu → **About This Mac**: "Chip: Apple M…" means Apple Silicon, "Processor: Intel" means Intel.

## How it works

### Windows

| You do | What happens |
|---|---|
| **Win+Shift+S** or **PrtSc**, snip like normal | Snip copies to clipboard as usual, *and* a small **✦ AI** bubble pops up next to your cursor |
| Click **AI** | Chat window opens with your snip attached — ask anything |
| Click **✕** or wait | Bubble disappears (default 3 s, adjustable 1–10 s). Hover pauses the timer |
| **Win+Shift+A** | Skips the Windows snip menu — drag an area, go straight to the AI chat |
| Tray icon | Left-click = AI snip. Right-click = settings, pause bubble, quit |

The bubble only appears for images copied by the Windows snip tool — copying an image in your browser won't trigger it (toggle in Settings).

### Mac

| You do | What happens |
|---|---|
| **⇧⌘1** (Shift+Command+1) | Drag an area, go straight to the AI chat. Works across multiple displays and Retina screens |
| **⇧⌘3 / ⇧⌘4 / ⇧⌘5**, screenshot like normal | macOS saves the file as usual, *and* the **✦ AI** bubble pops up next to your cursor |
| **⌃⇧⌘4** (copy screenshot to clipboard) | Same bubble |
| Click **AI** | Chat window opens with your screenshot attached |
| Click **✕** or wait | Bubble disappears (1–10 s, hover pauses it) |
| Menu-bar icon | Snip with AI, settings, pause bubble, quit. No Dock icon |

How the bubble works on Mac: macOS saves screenshots as files (on your Desktop unless you changed it in ⇧⌘5 → Options → Save to), so PrtSc AI watches that folder for new screenshots, and also watches the clipboard for ⌃⇧⌘4. Each screenshot shows the bubble once. Other images saved to the folder are ignored ("Only for screenshots" in Settings). macOS doesn't say which app copied an image, so any image copied to the clipboard shows the bubble.

Tip: macOS shows a floating thumbnail for a few seconds before it saves the file. For an instant bubble, press ⇧⌘5 → **Options** → untick **Show Floating Thumbnail**.

The hotkey can be changed in Settings (e.g. `Cmd+Shift+1`, `Ctrl+Option+Q`).

## Supported AI providers

| Provider | Format | Key |
|---|---|---|
| Claude (Anthropic) | Anthropic | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| ChatGPT (OpenAI) | OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) |
| Gemini (Google) — free tier | OpenAI-compatible | [aistudio.google.com](https://aistudio.google.com/apikey) |
| Grok (xAI) | OpenAI-compatible | [console.x.ai](https://console.x.ai) |
| DeepSeek | OpenAI-compatible | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| OpenRouter (hundreds of models) | OpenAI-compatible | [openrouter.ai](https://openrouter.ai/keys) |
| Mistral, Groq | OpenAI-compatible | their consoles |
| Ollama — local, free, offline | OpenAI-compatible | none |
| Anything else | Custom OpenAI / Anthropic-compatible | your own |

The model must accept **images**. Use **Fetch models** in Settings to pull the provider's live model list, then **Test with an image** to confirm it can see. For DeepSeek, only its vision model accepts images; its text-only models return an error.

API keys are never stored in a plain file:
- **Windows:** Windows Credential Manager. Other settings: `%APPDATA%\PrtSc AI\settings.json`.
- **Mac:** your login **Keychain** (service "PrtSc AI"). Other settings: `~/Library/Application Support/PrtSc AI/settings.json`.

## Install

### Windows

1. Download [`PrtSc-AI.exe`](https://github.com/AagamS06/PrtSc-AI/releases/latest/download/PrtSc-AI.exe) and double-click it. Nothing to install.
2. Windows may say *"Windows protected your PC"* because the app isn't code-signed. Click **More info → Run anyway**.
3. Settings open on first run: pick a provider, paste a key, pick a model, **Save**.
4. Snip with **Win+Shift+S** and click the **✦ AI** bubble, or press **Win+Shift+A**.

It starts with Windows by default (toggle in Settings).

### Mac

Needs macOS Sonoma 14.4 or later.

1. Download the `.dmg` for your Mac (table above) and open it.
2. Drag **PrtSc AI** into **Applications**.
3. Open it from Applications. The app isn't signed with an Apple Developer ID, so the first time macOS says it's from an unidentified developer / can't be checked:
   - **Right-click** (or Control-click) PrtSc AI → **Open** → **Open**, or
   - if there's no Open button: **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to the PrtSc AI message, then confirm.
4. **Screen Recording:** PrtSc AI asks for it so it can see what you snip. Click **Open System Settings**, turn on **PrtSc AI** under **Privacy & Security → Screen Recording**, and if macOS asks, choose **Quit & Reopen** (or quit PrtSc AI from its menu-bar icon and open it again).
5. macOS may also ask to let PrtSc AI access your **Desktop** folder. Allow it: that's how it sees new screenshots.
6. Settings open on first run: pick a provider, paste a key, pick a model, **Save**.
7. Take a screenshot (**⇧⌘4**) and click the **✦ AI** bubble, or press **⇧⌘1**.

PrtSc AI lives in the menu bar (no Dock icon) and opens at login by default (toggle in Settings).

## Updating

### Windows

Download the new `PrtSc-AI.exe` and double-click it. That's it:
- Your **API keys** are stored in Windows Credential Manager and your **settings** in `%APPDATA%\PrtSc AI`, not inside the .exe, so every new version picks them up automatically. No re-pasting.
- If an older version is running, the new one closes it and takes over (from v1.0.2 on).
- "Start with Windows" is re-pointed at the new .exe, so you can delete the old file. All releases: [Releases page](https://github.com/AagamS06/PrtSc-AI/releases).

### Mac

Quit PrtSc AI from its menu-bar icon, download the new `.dmg`, and drag PrtSc AI into Applications again (choose **Replace**). Then open it.
- Your **API keys** stay in your Keychain and your **settings** in `~/Library/Application Support/PrtSc AI`, so nothing needs re-entering. macOS may ask once whether the new version can use the saved key: click **Always Allow**.
- "Open at login" is re-pointed at the new app on every launch.
- Because the app is unsigned, macOS may ask you to re-allow **Screen Recording** after an update. Same steps as the first install.

## Build it yourself

**Windows** — needs [Python 3.10+](https://www.python.org/downloads/) (tick "Add Python to PATH").

- `build.bat` → builds `dist\PrtSc-AI.exe`
- `run.bat` → runs from source

**Mac** — needs Python 3.10+ ([python.org](https://www.python.org/downloads/macos/) or Homebrew).

- `./build.sh` → builds `dist/PrtSc AI.app` and `dist/PrtSc-AI-mac.dmg`
- `./run.sh` → runs from source (macOS asks for Screen Recording for your Terminal app in that case)

## Notes

- Windows 11: if PrtSc doesn't open the snip tool, turn on *Settings → Accessibility → Keyboard → Use the Print screen key to open screen capture*. Legacy full-screen PrtSc still triggers the bubble.
- If the hotkey is taken by another app, pick another one in Settings (e.g. `Ctrl+Alt+Q` on Windows, `Ctrl+Option+Q` on Mac).
- The Mac hotkey uses the standard system hot-key API, so it needs no Accessibility permission.
- Images are sent only to the provider you choose, only when you hit Send.

## Project layout

```
main.py       tray / menu-bar app, clipboard + screenshot watchers, wiring
ui.py         bubble, snip overlay, chat window, settings, Mac permission dialog
providers.py  OpenAI-compatible + Anthropic adapters
winsys.py     Windows: global hotkey + clipboard-owner detection (Win32 via ctypes)
macsys.py     Mac: global hotkey (Carbon), Screen Recording, screenshot folder, open at login
config.py     settings + Credential Manager / Keychain keys + start at login
tests/        provider tests (mock server), Mac logic tests, native Mac checks (CI)
```

MIT licensed.
