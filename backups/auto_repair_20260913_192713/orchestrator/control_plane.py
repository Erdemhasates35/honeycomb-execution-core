#!/usr/bin/env python3

import json
import os
import re
import subprocess
import time
import hashlib
import socket
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("CONTROL_PORT", "8787"))
HOST = os.getenv("CONTROL_HOST", "127.0.0.1")
STATE = ROOT / "orchestrator" / "state.json"
REGISTRY = ROOT / "orchestrator" / "registry.json"
PIDFILE = ROOT / "runtime" / "control_plane.pid"
LOGDIR = ROOT / "logs"

SOURCE_EXT = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".sh", ".bash", ".json"
}

SKIP = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".next",
    "dist",
    "build"
}

def safe_env():
    names = [
        "AUTO_PAPER",
        "AUTO_INTERVAL_SEC",
        "TARGET_PROFIT_PERCENT",
        "MAX_LOSS_PERCENT",
        "TESTNET_PORT",
        "TESTNET_RISK",
        "TESTNET_LEVERAGE",
        "TESTNET_TP_M",
        "TESTNET_SL_P",
        "TESTNET_HOLD_MAX",
        "TESTNET_INTERVAL",
        "TESTNET_COOLDOWN",
        "TESTNET_MAX_POS_USDT",
        "NET_MARGIN_TARGET_PCT",
        "CONSECUTIVE_LOSS_THRESHOLD",
        "SYMBOL_COOLDOWN_MIN",
        "ERROR_REPEAT_THRESHOLD",
        "MARGIN_PAUSE_MIN",
        "ATR_PERCENTILE_FLOOR",
        "MIN_ATR_PCT",
        "LOW_VOL_ATR_PCT",
        "LOW_VOL_RISK_MULT",
        "LOW_VOL_CONFIDENCE",
        "NORMAL_CONFIDENCE",
        "FEE_RATE",
        "COOLDOWN",
        "LIVE_SYMBOLS"
    ]

    out = {}

    for key in names:
        if key in os.environ:
            out[key] = os.environ[key]

    for secret in (
        "BINANCE_TESTNET_API_KEY",
        "BINANCE_TESTNET_SECRET",
        "BINANCE_API_KEY",
        "BINANCE_SECRET"
    ):
        out[secret] = "SET" if os.getenv(secret) else "NOT_SET"

    return out


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def inventory():
    engines = []
    files = []

    patterns = (
        "engine",
        "alpha",
        "brain",
        "nexus",
        "verify",
        "sovereign",
        "futures",
        "scalp"
    )

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if any(part in SKIP for part in path.parts):
            continue

        relative = path.relative_to(ROOT)

        if path.suffix not in SOURCE_EXT:
            continue

        try:
            size = path.stat().st_size
            digest = sha256(path)
            text = ""

            if (
                size < 2_000_000
                and path.suffix in {
                    ".py", ".js", ".mjs", ".cjs",
                    ".ts", ".sh", ".go"
                }
            ):
                text = path.read_text(errors="ignore")[:200000]

            score = sum(
                1
                for item in patterns
                if item in path.name.lower()
                or item in text.lower()
            )

            item = {
                "path": str(relative),
                "size": size,
                "sha256": digest
            }

            files.append(item)

            if score >= 2:
                engines.append({
                    "path": str(relative),
                    "score": score,
                    "sha256": digest
                })

        except Exception as exc:
            files.append({
                "path": str(relative),
                "error": str(exc)
            })

    data = {
        "generated_at": time.time(),
        "files": files,
        "engines": sorted(
            engines,
            key=lambda x: -x["score"]
        )
    }

    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)

    (runtime / "inventory.json").write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False
        )
    )

    registry = json.loads(REGISTRY.read_text())
    registry["engines"] = data["engines"]

    REGISTRY.write_text(
        json.dumps(
            registry,
            indent=2,
            ensure_ascii=False
        )
    )

    return data


def git_status():
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()

        status = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL
        )

        return {
            "branch": branch,
            "dirty": bool(status.strip()),
            "status": status.splitlines()[-100:]
        }

    except Exception as exc:
        return {"error": str(exc)}


def port_probe(port):
    sock = socket.socket()
    sock.settimeout(0.35)

    try:
        return sock.connect_ex(
            ("127.0.0.1", port)
        ) == 0
    finally:
        sock.close()


def recent_logs(limit=120):
    rows = []

    if not LOGDIR.exists():
        return rows

    files = sorted(
        LOGDIR.glob("*"),
        key=lambda x: x.stat().st_mtime if x.exists() else 0,
        reverse=True
    )[:8]

    for path in files:
        if not path.is_file():
            continue

        try:
            lines = path.read_text(
                errors="replace"
            ).splitlines()

            for line in lines[-limit:]:
                if re.search(
                    r"(api[_ -]?key|secret|private[_ -]?key|token)",
                    line,
                    re.I
                ):
                    line = "[REDACTED]"

                rows.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": line[-1000:]
                })

        except Exception:
            pass

    return rows[-limit:]


def database_stats():
    import sqlite3

    result = []

    for path in ROOT.rglob("*.db"):
        if any(part in SKIP for part in path.parts):
            continue

        try:
            connection = sqlite3.connect(
                str(path),
                timeout=1
            )

            tables = connection.execute(
                "select name from sqlite_master where type='table'"
            ).fetchall()

            counts = {}

            for table, in tables[:50]:
                try:
                    counts[table] = connection.execute(
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()[0]
                except Exception:
                    pass

            connection.close()

            result.append({
                "db": str(path.relative_to(ROOT)),
                "tables": counts
            })

        except Exception as exc:
            result.append({
                "db": str(path.relative_to(ROOT)),
                "error": str(exc)
            })

    return result


def current_status():
    inv = inventory()

    launcher = None

    for name in (
        "run_nexus_testnet.sh",
        "run_testnet.sh",
        "fix_testnet_stack.sh"
    ):
        candidate = ROOT / name

        if candidate.exists():
            launcher = str(candidate)
            break

    return {
        "time": time.time(),
        "project": ROOT.name,
        "mode": os.getenv(
            "HONEYCOMB_MODE",
            "TESTNET"
        ).upper(),
        "control_plane": {
            "host": HOST,
            "port": PORT
        },
        "execution_ports": {
            "8000": port_probe(8000),
            "8100": port_probe(8100)
        },
        "pid": os.getpid(),
        "git": git_status(),
        "env": safe_env(),
        "engine_count": len(inv["engines"]),
        "source_file_count": len(inv["files"]),
        "databases": database_stats(),
        "launcher": launcher
    }


class Handler(BaseHTTPRequestHandler):

    def send_json(self, status, payload):
        body = json.dumps(
            payload,
            ensure_ascii=False
        ).encode()

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header(
            "Cache-Control",
            "no-store"
        )
        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/":
            body = (
                ROOT / "dashboard" / "index.html"
            ).read_bytes()

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )
            self.send_header(
                "Cache-Control",
                "no-store"
            )
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/status":
            self.send_json(
                200,
                current_status()
            )
            return

        if parsed.path == "/api/engines":
            self.send_json(
                200,
                inventory()["engines"]
            )
            return

        if parsed.path == "/api/files":
            self.send_json(
                200,
                inventory()["files"]
            )
            return

        if parsed.path == "/api/logs":
            try:
                limit = min(
                    int(query.get("n", ["120"])[0]),
                    500
                )
            except Exception:
                limit = 120

            self.send_json(
                200,
                recent_logs(limit)
            )
            return

        if parsed.path == "/api/mode":
            self.send_json(
                200,
                {
                    "mode": os.getenv(
                        "HONEYCOMB_MODE",
                        "TESTNET"
                    ).upper()
                }
            )
            return

        self.send_json(
            404,
            {"error": "not_found"}
        )

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path != "/api/mode":
            self.send_json(
                404,
                {"error": "not_found"}
            )
            return

        length = int(
            self.headers.get(
                "Content-Length",
                "0"
            )
        )

        try:
            data = json.loads(
                self.rfile.read(length) or b"{}"
            )
        except Exception:
            self.send_json(
                400,
                {"error": "invalid_json"}
            )
            return

        mode = str(
            data.get("mode", "")
        ).upper()

        if mode not in {
            "TESTNET",
            "PAPER",
            "LIVE"
        }:
            self.send_json(
                400,
                {
                    "error":
                    "mode must be TESTNET, PAPER or LIVE"
                }
            )
            return

        if (
            mode == "LIVE"
            and os.getenv("LIVE_ARMED") != "1"
        ):
            self.send_json(
                403,
                {
                    "error":
                    "LIVE_ARMED=1 required"
                }
            )
            return

        STATE.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "changed_at": time.time()
                },
                indent=2
            )
        )

        self.send_json(
            200,
            {
                "ok": True,
                "mode": mode
            }
        )

    def log_message(self, *args):
        pass


def main():
    (ROOT / "runtime").mkdir(
        exist_ok=True
    )

    PIDFILE.write_text(
        str(os.getpid())
    )

    inventory()

    print(
        f"HONEYCOMB CONTROL PLANE "
        f"http://{HOST}:{PORT}",
        flush=True
    )

    ThreadingHTTPServer(
        (HOST, PORT),
        Handler
    ).serve_forever()


if __name__ == "__main__":
    main()
