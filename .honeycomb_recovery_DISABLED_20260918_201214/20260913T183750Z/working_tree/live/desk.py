#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Local control desk for live engines (Termux). No API secrets in responses."""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "live", "desk_state.json")
PORT = int(os.environ.get("DESK_PORT", "8788"))

DEFAULT = {
    "apex": False,
    "helix": False,
    "sniper": False,
    "venue": "usdt",
    "updated": 0,
}


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return {**DEFAULT, **json.load(f)}
    except Exception:
        return dict(DEFAULT)


def save_state(s):
    s["updated"] = int(time.time())
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/status"):
            self._json(200, {"ok": 1, "state": load_state(), "engines": {
                "apex": "live/apex_usdt.py",
                "helix": "live/helix_coin.py",
                "sniper": "live/maker_sniper.py",
            }})
            return
        if path == "/commands":
            st = load_state()
            cmds = []
            if st.get("apex"):
                cmds.append("python3 live/apex_usdt.py")
            if st.get("helix"):
                cmds.append("python3 live/helix_coin.py")
            if st.get("sniper"):
                cmds.append("VENUE=%s python3 live/maker_sniper.py" % st.get("venue", "usdt"))
            self._json(200, {"commands": cmds, "state": st})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            body = {}
        st = load_state()
        if path.startswith("/engine/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3:
                eng, action = parts[1], parts[2]
                if eng in ("apex", "helix", "sniper"):
                    st[eng] = action == "on"
                    save_state(st)
                    self._json(200, {"ok": 1, "state": st})
                    return
        if path == "/venue":
            v = (body.get("venue") or "usdt").lower()
            if v not in ("usdt", "coin"):
                self._json(400, {"error": "venue must be usdt|coin"})
                return
            st["venue"] = v
            save_state(st)
            self._json(200, {"ok": 1, "state": st})
            return
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print("[DESK] " + (fmt % args), flush=True)


if __name__ == "__main__":
    save_state(load_state())
    print("Honeycomb live desk on 0.0.0.0:%d" % PORT, flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
