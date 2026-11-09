# PrtSc AI

**Circle to Search, for Windows.** Snip any part of your screen and ask AI about it — Claude, ChatGPT, Gemini, Grok, DeepSeek, OpenRouter, Ollama or any OpenAI-compatible API.

## How it works

| You do | What happens |
|---|---|
| **Win+Shift+S** or **PrtSc**, snip like normal | Snip copies to clipboard as usual, *and* a small **✦ AI** bubble pops up next to your cursor |
| Click **AI** | Chat window opens with your snip attached — ask anything |
| Click **✕** or wait | Bubble disappears (default 3 s, adjustable 1–10 s). Hover pauses the timer |
| **Win+Shift+A** | Skips the Windows snip menu — drag an area, go straight to the AI chat |
| Tray icon | Left-click = AI snip. Right-click = settings, pause bubble, quit |

The bubble only appears for images copied by the Windows snip tool — copying an image in your browser won't trigger it (toggle in Settings).

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

API keys are stored in **Windows Credential Manager**, never in a plain file. Other settings live in `%APPDATA%\PrtSc AI\settings.json`.

## Download

**[⬇ Download PrtSc-AI.exe](https://github.com/AagamS06/PrtSc-AI/releases/latest/download/PrtSc-AI.exe)** (Windows 10/11, single file, nothing to install)

1. Double-click `PrtSc-AI.exe`.
2. Windows may say *"Windows protected your PC"* because the app isn't code-signed. Click **More info → Run anyway**.
3. Settings open on first run: pick a provider, paste a key, pick a model, **Save**.
4. Snip with **Win+Shift+S** and click the **✦ AI** bubble, or press **Win+Shift+A**.

It starts with Windows by default (toggle in Settings).

### Updating

Download the new `PrtSc-AI.exe` and double-click it. That's it:
- Your **API keys** are stored in Windows Credential Manager and your **settings** in `%APPDATA%\PrtSc AI`, not inside the .exe, so every new version picks them up automatically. No re-pasting.
- If an older version is running, the new one closes it and takes over (from v1.0.2 on).
- "Start with Windows" is re-pointed at the new .exe, so you can delete the old file. All releases: [Releases page](https://github.com/AagamS06/PrtSc-AI/releases).

### Build it yourself

Needs [Python 3.10+](https://www.python.org/downloads/) (tick "Add Python to PATH").

- `build.bat` → builds `dist\PrtSc-AI.exe`
- `run.bat` → runs from source

## Notes

- Windows 11: if PrtSc doesn't open the snip tool, turn on *Settings → Accessibility → Keyboard → Use the Print screen key to open screen capture*. Legacy full-screen PrtSc still triggers the bubble.
- If Win+Shift+A is taken by another app, pick another hotkey in Settings (e.g. `Ctrl+Alt+Q`).
- Images are sent only to the provider you choose, only when you hit Send.

## Project layout

```
main.py       tray app, clipboard watcher, wiring
ui.py         bubble, snip overlay, chat window, settings
providers.py  OpenAI-compatible + Anthropic adapters
winsys.py     global hotkey + clipboard-owner detection (Win32 via ctypes)
config.py     settings + Credential Manager keys + start-with-Windows
```

MIT licensed.
