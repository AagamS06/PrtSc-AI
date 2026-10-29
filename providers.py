"""AI provider adapters.

Two wire formats cover every mainstream API:
  * OpenAI-compatible chat completions  -> ChatGPT, Gemini, Grok, DeepSeek,
    OpenRouter, Mistral, Groq, Ollama (local), LM Studio, anything custom.
  * Anthropic Messages                  -> Claude.

Plain `requests`, no vendor SDKs, so the .exe stays small.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import requests

TIMEOUT = 120


@dataclass(frozen=True)
class Preset:
    name: str
    kind: str          # "openai" or "anthropic"
    base_url: str
    key_url: str       # where to get a key
    needs_key: bool = True
    hint: str = ""     # shown under the model box


PRESETS: list[Preset] = [
    Preset("Claude (Anthropic)", "anthropic", "https://api.anthropic.com/v1",
           "https://console.anthropic.com/settings/keys"),
    Preset("ChatGPT (OpenAI)", "openai", "https://api.openai.com/v1",
           "https://platform.openai.com/api-keys"),
    Preset("Gemini (Google)", "openai",
           "https://generativelanguage.googleapis.com/v1beta/openai",
           "https://aistudio.google.com/apikey",
           hint="Free tier available."),
    Preset("Grok (xAI)", "openai", "https://api.x.ai/v1",
           "https://console.x.ai"),
    Preset("DeepSeek", "openai", "https://api.deepseek.com",
           "https://platform.deepseek.com/api_keys",
           hint="Only DeepSeek's vision model accepts images "
                "(e.g. deepseek-flash). Text-only models return a 400."),
    Preset("OpenRouter (many models)", "openai", "https://openrouter.ai/api/v1",
           "https://openrouter.ai/keys",
           hint="One key, hundreds of models. Pick one with image input."),
    Preset("Mistral", "openai", "https://api.mistral.ai/v1",
           "https://console.mistral.ai/api-keys"),
    Preset("Groq", "openai", "https://api.groq.com/openai/v1",
           "https://console.groq.com/keys"),
    Preset("Ollama (local, free)", "openai", "http://localhost:11434/v1",
           "https://ollama.com/download", needs_key=False,
           hint="Runs on your PC. Pull a vision model, e.g. `ollama pull llava`."),
    Preset("Custom (OpenAI-compatible)", "openai", "",
           "", needs_key=False,
           hint="Any server that speaks the OpenAI chat-completions format."),
    Preset("Custom (Anthropic-compatible)", "anthropic", "",
           "", needs_key=False),
]

PRESETS_BY_NAME = {p.name: p for p in PRESETS}

SYSTEM_PROMPT = (
    "You are a helpful assistant built into a Windows screenshot tool. "
    "The user captured part of their screen and is asking about it. "
    "Answer directly and concisely. Use markdown when it helps."
)


class ProviderError(Exception):
    pass


def _raise_for(resp: requests.Response) -> None:
    if resp.ok:
        return
    try:
        data = resp.json()
        err = data.get("error", data)
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:
        msg = resp.text[:500]
    hints = {
        400: "Bad request. If the message mentions images, this model can't see images. Pick a vision model.",
        401: "API key rejected. Check it in Settings.",
        403: "Key lacks access to this model or region.",
        404: "Model or endpoint not found. Check model name and base URL.",
        429: "Rate limit or out of credit.",
    }
    hint = hints.get(resp.status_code, "")
    raise ProviderError(f"HTTP {resp.status_code}: {msg}" + (f"\n\n{hint}" if hint else ""))


def _b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")


# ---------------------------------------------------------------- messages
# Internal history format: list of {"role": "user"|"assistant", "text": str, "image": bytes|None}

def _openai_messages(history: list[dict]) -> list[dict]:
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        if m.get("image") is not None:
            out.append({"role": m["role"], "content": [
                {"type": "text", "text": m["text"]},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + _b64(m["image"])}},
            ]})
        else:
            out.append({"role": m["role"], "content": m["text"]})
    return out


def _anthropic_messages(history: list[dict]) -> list[dict]:
    out = []
    for m in history:
        if m.get("image") is not None:
            out.append({"role": m["role"], "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": _b64(m["image"])}},
                {"type": "text", "text": m["text"]},
            ]})
        else:
            out.append({"role": m["role"], "content": m["text"]})
    return out


# ---------------------------------------------------------------- calls

def chat(kind: str, base_url: str, api_key: str, model: str, history: list[dict]) -> str:
    base = base_url.rstrip("/")
    if not base:
        raise ProviderError("No base URL set. Open Settings.")
    if not model:
        raise ProviderError("No model set. Open Settings and pick one.")

    if kind == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        body = {"model": model, "max_tokens": 4096, "system": SYSTEM_PROMPT,
                "messages": _anthropic_messages(history)}
        r = requests.post(f"{base}/messages", headers=headers, json=body, timeout=TIMEOUT)
        _raise_for(r)
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    if "openrouter.ai" in base:
        headers["HTTP-Referer"] = "https://github.com/prtsc-ai"
        headers["X-Title"] = "PrtSc AI"
    body = {"model": model, "messages": _openai_messages(history)}
    r = requests.post(f"{base}/chat/completions", headers=headers, json=body, timeout=TIMEOUT)
    _raise_for(r)
    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError(f"Unexpected response: {str(data)[:500]}")
    if isinstance(content, list):  # some servers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def list_models(kind: str, base_url: str, api_key: str) -> list[str]:
    """Ask the provider which models exist, so names never go stale."""
    base = base_url.rstrip("/")
    if not base:
        raise ProviderError("No base URL set.")
    if kind == "anthropic":
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        r = requests.get(f"{base}/models", headers=headers, params={"limit": 100}, timeout=30)
    else:
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        r = requests.get(f"{base}/models", headers=headers, timeout=30)
    _raise_for(r)
    data = r.json()
    items = data.get("data") or data.get("models") or []
    ids = []
    for it in items:
        mid = it.get("id") or it.get("name") if isinstance(it, dict) else str(it)
        if mid:
            ids.append(mid.removeprefix("models/"))
    return sorted(set(ids))
