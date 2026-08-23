#!/usr/bin/env python3
"""Production UI gateway for the Honeycomb control plane and execution bridge."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
HOST = os.getenv("UI_CONTROL_HOST", "127.0.0.1")
PORT = int(os.getenv("UI_CONTROL_PORT", "8788"))
CONTROL_URL = os.getenv("HONEYCOMB_CONTROL_URL", "http://127.0.0.1:8787").rstrip("/")
BRIDGE_URL = os.getenv("HONEYCOMB_BRIDGE_URL", "http://127.0.0.1:8100").rstrip("/")
ENGINE_URL = os.getenv("HONEYCOMB_ENGINE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("UI_PROXY_TIMEOUT_SEC", "3.5"))

UI_PROXY_ROUTES: dict[str, tuple[str, str]] = {
    "/api/ui/status": ("GET", f"{CONTROL_URL}/api/status"),
    "/api/ui/engines": ("GET", f"{CONTROL_URL}/api/engines"),
    "/api/ui/files": ("GET", f"{CONTROL_URL}/api/files"),
    "/api/ui/quality": ("GET", f"{CONTROL_URL}/api/quality"),
    "/api/ui/logs": ("GET", f"{CONTROL_URL}/api/logs"),
    "/api/ui/overview": ("GET", f"{BRIDGE_URL}/summary"),
    "/api/ui/positions": ("GET", f"{BRIDGE_URL}/positions"),
    "/api/ui/journal": ("GET", f"{BRIDGE_URL}/journal"),
    "/api/ui/bridge-status": ("GET", f"{BRIDGE_URL}/status"),
    "/api/ui/bridge-health": ("GET", f"{BRIDGE_URL}/health"),
    "/api/ui/engine-health": ("GET", f"{ENGINE_URL}/health"),
}


def normalize_mode(value: str) -> str | None:
    mode = str(value).upper().strip()
    return mode if mode in {"TESTNET", "PAPER", "SHADOW", "LIVE"} else None


def ui_capabilities() -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "data_policy": "REAL_BACKEND_ONLY",
        "mode": {"supported": ["TESTNET", "PAPER", "SHADOW", "LIVE"], "live_backend_gate": "LIVE_ARMED=1"},
        "orders": {"browser_submission": False, "reason": "Execution secrets remain backend-only."},
        "routes": sorted(UI_PROXY_ROUTES),
        "sources": {"control": CONTROL_URL, "bridge": BRIDGE_URL, "engine": ENGINE_URL},
    }


def fetch_json(url: str, method: str = "GET", body: bytes | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url, method=method, data=body, headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return response.status, {"error": "UPSTREAM_NON_JSON"}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw or "UPSTREAM_HTTP_ERROR"}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 503, {"error": "UPSTREAM_UNAVAILABLE", "detail": str(exc)}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-ID")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_json(204, None)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            file = ROOT / "dashboard" / "index.html"
            body = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/ui/capabilities":
            self.send_json(200, ui_capabilities())
            return
        if path == "/api/ui/mode":
            status, payload = fetch_json(f"{CONTROL_URL}/api/status")
            mode = payload.get("mode") if isinstance(payload, dict) else None
            self.send_json(status, {"mode": mode, "backend": payload})
            return
        route = UI_PROXY_ROUTES.get(path)
        if route is None or route[0] != "GET":
            self.send_json(404, {"error": "NOT_FOUND"})
            return
        status, payload = fetch_json(route[1])
        self.send_json(status, payload)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/ui/mode":
            self.send_json(404, {"error": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "INVALID_JSON"})
            return
        mode = normalize_mode(str(payload.get("mode", "")))
        if mode is None:
            self.send_json(400, {"error": "MODE_MUST_BE_TESTNET_PAPER_SHADOW_OR_LIVE"})
            return
        if mode == "SHADOW":
            self.send_json(409, {"error": "SHADOW_REQUIRES_BACKEND_SHADOW_STATE", "mode": "SHADOW"})
            return
        status, result = fetch_json(f"{CONTROL_URL}/api/mode", method="POST", body=json.dumps({"mode": mode}).encode("utf-8"))
        self.send_json(status, result)

    def log_message(self, *_args: Any) -> None:
        return


def main() -> None:
    print(f"HONEYCOMB UI GATEWAY http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
