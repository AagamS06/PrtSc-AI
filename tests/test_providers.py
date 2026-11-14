"""Provider adapters against a local mock server (no real API keys).
Run: python tests/test_providers.py"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import providers  # noqa: E402

providers.BACKOFF = [0, 0, 0]  # don't sleep in tests
STATE = {"fail": 0, "calls": 0, "last": None}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            self._send(200, {"data": [{"id": "models/vision-b"}, {"id": "vision-a"}]})
        else:
            self._send(404, {"error": {"message": "nope"}})

    def do_POST(self):
        STATE["calls"] += 1
        n = int(self.headers.get("content-length", 0))
        STATE["last"] = (self.path, dict(self.headers), json.loads(self.rfile.read(n)))
        if STATE["fail"]:
            STATE["fail"] -= 1
            return self._send(503, [{"error": {"message": "high demand", "status": "UNAVAILABLE"}}])
        if self.path.endswith("/chat/completions"):
            self._send(200, {"choices": [{"message": {"content": "red"}}]})
        elif self.path.endswith("/messages"):
            self._send(200, {"content": [{"type": "text", "text": "red"}]})
        elif self.path.endswith("/bad"):
            self._send(401, {"error": {"message": "invalid key"}})


def main() -> int:
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    hist = [{"role": "user", "text": "colour?", "image": b"\x89PNG fake"}]

    assert providers.chat("openai", base, "k", "m", hist) == "red"
    path, headers, body = STATE["last"]
    assert path == "/v1/chat/completions" and headers["authorization"] == "Bearer k"
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

    assert providers.chat("anthropic", base, "k", "m", hist) == "red"
    path, headers, body = STATE["last"]
    assert path == "/v1/messages" and headers["x-api-key"] == "k"
    assert body["messages"][0]["content"][0]["source"]["media_type"] == "image/png"

    # overloaded twice, then OK: retried automatically
    STATE["fail"], STATE["calls"] = 2, 0
    seen = []
    assert providers.chat("openai", base, "k", "m", hist, on_retry=lambda *a: seen.append(a)) == "red"
    assert STATE["calls"] == 3 and len(seen) == 2

    # always overloaded: friendly message after MAX_ATTEMPTS
    STATE["fail"], STATE["calls"] = 99, 0
    try:
        providers.chat("openai", base, "k", "m", hist, provider="Gemini")
        raise AssertionError("expected ProviderError")
    except providers.ProviderError as e:
        assert "overloaded" in str(e) and STATE["calls"] == providers.MAX_ATTEMPTS
    STATE["fail"] = 0

    assert providers.list_models("openai", base, "k") == ["vision-a", "vision-b"]
    for missing in (dict(base_url=""), dict(model="")):
        args = dict(kind="openai", base_url=base, api_key="k", model="m", history=hist) | missing
        try:
            providers.chat(**args)
            raise AssertionError("expected ProviderError")
        except providers.ProviderError:
            pass
    srv.shutdown()
    print("provider tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
