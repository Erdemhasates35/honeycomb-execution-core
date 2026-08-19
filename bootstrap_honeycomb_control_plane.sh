#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

mkdir -p orchestrator dashboard scripts runtime logs reports docs/superpowers/plans

cat > docs/superpowers/plans/2026-08-19-honeycomb-control-plane.md <<'PLAN'
# Honeycomb Control Plane Implementation Plan

**Goal:** Existing Honeycomb engines become one modular control plane supporting TESTNET, PAPER and LIVE modes with browser telemetry and GitHub synchronization.

**Architecture:** Existing engines remain execution modules. A control plane sits above them, inventories them, monitors ports/processes/logs/databases, exposes browser telemetry, and starts only the selected existing execution launcher.

**Tech Stack:** Bash, Python standard library, SQLite, Node.js, TypeScript, Git, optional Vercel and Cloudflare Tunnel.

**Global Constraints**
- Preserve existing source and historical engines.
- Never print API secrets.
- Keep .env, databases, logs and runtime state outside Git.
- Support TESTNET, PAPER and LIVE.
- Existing ports 8000 and 8100 remain untouched.
- Control plane uses port 8787.
- LIVE requires explicit LIVE_ARMED=1.
PLAN

cat > orchestrator/registry.json <<'JSON'
{
  "project": "honeycomb-execution-core",
  "control_plane": {
    "host": "127.0.0.1",
    "port": 8787
  },
  "execution_ports": [8000, 8100],
  "modes": ["TESTNET", "PAPER", "LIVE"],
  "engines": []
}
JSON

cat > orchestrator/control_plane.py <<'PY'
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
PY

chmod 700 orchestrator/control_plane.py

cat > dashboard/index.html <<'HTML'
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HONEYCOMB CONTROL PLANE</title>
<style>
body{
margin:0;
background:#080b10;
color:#dfe7ef;
font:14px system-ui,sans-serif
}
main{
max-width:1400px;
margin:auto;
padding:18px
}
h1{
margin:0 0 14px;
font-size:22px
}
.grid{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(220px,1fr));
gap:10px
}
.card{
background:#111720;
border:1px solid #26303b;
border-radius:10px;
padding:14px;
margin-bottom:10px
}
.v{
font-size:22px;
font-weight:700;
margin-top:6px
}
pre{
white-space:pre-wrap;
max-height:420px;
overflow:auto;
background:#06080b;
padding:12px;
border-radius:8px
}
small{
opacity:.7
}
.ok{
color:#79e2a0
}
.bad{
color:#ff7d7d
}
</style>
</head>

<body>
<main>

<h1>
HONEYCOMB / QUANTUM NEXUS CONTROL PLANE
</h1>

<div class="grid" id="cards"></div>

<div class="card">
<b>ENGINE INVENTORY</b>
<pre id="engines">loading...</pre>
</div>

<div class="card">
<b>DATABASE / EXECUTION TELEMETRY</b>
<pre id="db">loading...</pre>
</div>

<div class="card">
<b>RECENT LOG STREAM</b>
<pre id="logs">loading...</pre>
</div>

</main>

<script>

const esc = value =>
String(value ?? "")
.replace(
/[&<>]/g,
character => ({
"&":"&amp;",
"<":"&lt;",
">":"&gt;"
}[character])
);

async function tick(){

try{

const status =
await (
await fetch("/api/status")
).json();

const card =
(key,value,ok=true) =>
`<div class="card">
<small>${esc(key)}</small>
<div class="v ${ok ? "ok" : "bad"}">
${esc(value)}
</div>
</div>`;

document.querySelector("#cards")
.innerHTML = [

card(
"MODE",
status.mode
),

card(
"CONTROL PLANE",
`${status.control_plane.host}:${status.control_plane.port}`
),

card(
"ENGINE :8000",
status.execution_ports["8000"]
? "UP"
: "DOWN",
status.execution_ports["8000"]
),

card(
"BRIDGE :8100",
status.execution_ports["8100"]
? "UP"
: "DOWN",
status.execution_ports["8100"]
),

card(
"ENGINES",
status.engine_count
),

card(
"SOURCE FILES",
status.source_file_count
),

card(
"GIT",
status.git?.dirty
? "DIRTY"
: "CLEAN",
!status.git?.dirty
),

card(
"BRANCH",
status.git?.branch || "?"
)

].join("");

const engines =
await (
await fetch("/api/engines")
).json();

document.querySelector("#engines")
.textContent =
engines
.map(
x =>
`${x.path} | score=${x.score}`
)
.join("\n");

document.querySelector("#db")
.textContent =
JSON.stringify(
status.databases,
null,
2
);

const logs =
await (
await fetch("/api/logs?n=120")
).json();

document.querySelector("#logs")
.textContent =
logs
.map(
x =>
`[${x.file}] ${x.line}`
)
.join("\n");

}catch(error){

document.querySelector("#cards")
.innerHTML =
'<div class="card bad">CONTROL PLANE OFFLINE</div>';

}

}

tick();
setInterval(tick,1000);

</script>
</body>
</html>
HTML

cat > scripts/repair_env_format.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

if [ ! -f .env ]; then
    echo "ENV=NOT_FOUND"
    exit 0
fi

cp .env \
".env.backup.$(date +%Y%m%d-%H%M%S)"

python - <<'PY'
from pathlib import Path
import re

path = Path(".env")
output = []
invalid = []

for number, line in enumerate(
    path.read_text(
        errors="replace"
    ).splitlines(),
    1
):

    line = line.rstrip("\r")

    if (
        not line.strip()
        or line.lstrip().startswith("#")
    ):
        output.append(line)
        continue

    match = re.match(
        r'^([A-Za-z_][A-Za-z0-9_]*)=\s+(.*)$',
        line
    )

    if match:
        line = (
            f"{match.group(1)}="
            f"{match.group(2)}"
        )

    if not re.match(
        r'^[A-Za-z_][A-Za-z0-9_]*=',
        line
    ):
        invalid.append(
            (
                number,
                line[:100]
            )
        )

    output.append(line)

path.write_text(
    "\n".join(output) + "\n"
)

print("ENV_FORMAT=REPAIRED")

if invalid:
    print(
        "ENV_INVALID_LINES=",
        invalid
    )
    raise SystemExit(31)
PY

echo "ENV_BACKUP_CREATED=YES"
SH

chmod 700 scripts/repair_env_format.sh

bash scripts/repair_env_format.sh

cat > scripts/testnet_auth_probe.py <<'PY'
#!/usr/bin/env python3

import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import json

base = os.environ.get(
    "BINANCE_TESTNET_URL",
    "https://testnet.binancefuture.com"
).rstrip("/")

key = os.environ.get(
    "BINANCE_TESTNET_API_KEY",
    ""
)

secret = os.environ.get(
    "BINANCE_TESTNET_SECRET",
    ""
)

if not key or not secret:
    print(
        "TESTNET_AUTH=NOT_CONFIGURED"
    )
    raise SystemExit(2)


def get(path, params=None, signed=False):

    params = params or {}

    if signed:

        params["timestamp"] = int(
            time.time() * 1000
        )

        params["recvWindow"] = 5000

        query = urllib.parse.urlencode(
            params
        )

        params["signature"] = hmac.new(
            secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

    query = urllib.parse.urlencode(
        params
    )

    request = urllib.request.Request(
        base + path + "?" + query,
        headers={
            "X-MBX-APIKEY": key
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=12
        ) as response:

            return (
                response.status,
                json.loads(
                    response.read().decode()
                )
            )

    except urllib.error.HTTPError as error:

        raw = error.read().decode(
            errors="replace"
        )

        try:
            data = json.loads(raw)
        except Exception:
            data = {
                "raw": raw[:300]
            }

        return error.code, data


status, public = get(
    "/fapi/v1/time"
)

print(
    "PUBLIC_STATUS=",
    status
)

if status != 200:
    raise SystemExit(10)


status, exchange_info = get(
    "/fapi/v1/exchangeInfo"
)

print(
    "EXCHANGEINFO_STATUS=",
    status
)

if status != 200:
    raise SystemExit(11)


status, account = get(
    "/fapi/v2/account",
    signed=True
)

print(
    "AUTH_STATUS=",
    status
)

if (
    isinstance(account, dict)
    and account.get("code") == -2015
):

    print("AUTH=-2015")
    raise SystemExit(2015)

if status != 200:

    print(
        "AUTH_ERROR_CODE=",
        account.get("code")
        if isinstance(account, dict)
        else "UNKNOWN"
    )

    raise SystemExit(12)

print(
    "TESTNET_AUTH=PASS"
)

print(
    "ACCOUNT_ASSET_COUNT=",
    len(account.get("assets", []))
)

print(
    "ACCOUNT_POSITION_COUNT=",
    len(account.get("positions", []))
)
PY

chmod 700 scripts/testnet_auth_probe.py

if [ -f .env ]; then
    set -a
    . .env
    set +a
    python scripts/testnet_auth_probe.py || true
fi

cat > scripts/verify_control_plane.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

echo "=== HONEYCOMB CONTROL PLANE VERIFY ==="

python -m py_compile \
    orchestrator/control_plane.py \
    scripts/testnet_auth_probe.py

echo "PYTHON=PASS"

if command -v node >/dev/null 2>&1; then

    while IFS= read -r -d '' file; do

        node --check "$file" >/dev/null

    done < <(
        find . \
        -type f \
        \( \
        -name '*.js' \
        -o -name '*.mjs' \
        -o -name '*.cjs' \
        \) \
        -not -path './node_modules/*' \
        -not -path './.git/*' \
        -print0
    )

    echo "NODE=PASS"

fi

if [ -x "./node_modules/.bin/tsc" ]; then

    ./node_modules/.bin/tsc --noEmit

    echo "TSC=PASS"

fi

git diff --check

echo "GIT_DIFF_CHECK=PASS"

for key in \
BINANCE_TESTNET_API_KEY \
BINANCE_TESTNET_SECRET \
BINANCE_TESTNET_URL
do

    value="${!key:-}"

    if [ -n "$value" ]; then

        echo \
        "$key=SET length=${#value}"

    else

        echo "$key=NOT_SET"

    fi

done

echo \
"DASHBOARD=http://127.0.0.1:8787"
SH

chmod 700 scripts/verify_control_plane.sh

cat > scripts/start_control_plane.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

mkdir -p runtime logs

if [
    -f runtime/control_plane.pid
] && kill -0 "$(
    cat runtime/control_plane.pid
)" 2>/dev/null; then

    echo "CONTROL_PLANE=ALREADY_RUNNING"

else

    nohup python \
        orchestrator/control_plane.py \
        >> logs/control_plane.log 2>&1 &

    echo $! \
        > runtime/control_plane.pid

    sleep 1

fi

echo \
"LOCAL_URL=http://127.0.0.1:8787"

if command -v termux-open-url >/dev/null 2>&1; then
    termux-open-url \
        "http://127.0.0.1:8787" || true
fi
SH

chmod 700 scripts/start_control_plane.sh

cat > scripts/start_testnet.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

export HONEYCOMB_MODE=TESTNET

bash scripts/start_control_plane.sh

LAUNCHER=""

for file in \
    run_nexus_testnet.sh \
    run_testnet.sh \
    fix_testnet_stack.sh
do

    if [
        -x "$file"
    ] || [
        -f "$file"
    ]; then

        LAUNCHER="$file"
        break

    fi

done

if [ -n "$LAUNCHER" ]; then

    echo \
    "TESTNET_LAUNCHER=$LAUNCHER"

    nohup bash \
        "$LAUNCHER" \
        >> logs/testnet_launcher.log 2>&1 &

    echo $! \
        > runtime/testnet_launcher.pid

else

    echo \
    "TESTNET_LAUNCHER=NOT_FOUND"

fi

echo \
"DASHBOARD=http://127.0.0.1:8787"
SH

chmod 700 scripts/start_testnet.sh

cat > scripts/start_live.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

if [ -f .env ]; then
    set -a
    . .env
    set +a
fi

[
    "${LIVE_ARMED:-0}"
    = "1"
] || {
    echo "LIVE_ARMED=1 required"
    exit 41
}

export HONEYCOMB_MODE=LIVE

bash scripts/start_control_plane.sh

LAUNCHER=""

for file in \
    run_nexus_live.sh \
    engine_live.py \
    engine_live2.py
do

    if [ -f "$file" ]; then

        LAUNCHER="$file"
        break

    fi

done

[
    -n "$LAUNCHER"
] || {
    echo "LIVE_LAUNCHER=NOT_FOUND"
    exit 42
}

echo \
"LIVE_LAUNCHER=$LAUNCHER"

case "$LAUNCHER" in

    *.py)

        nohup python \
            "$LAUNCHER" \
            >> logs/live_launcher.log 2>&1 &

        ;;

    *.sh)

        nohup bash \
            "$LAUNCHER" \
            >> logs/live_launcher.log 2>&1 &

        ;;

esac

echo $! \
    > runtime/live_launcher.pid

echo \
"DASHBOARD=http://127.0.0.1:8787"
SH

chmod 700 scripts/start_live.sh

cat > scripts/sync_all.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

touch .gitignore

for item in \
    ".env" \
    ".env.*" \
    "*.db" \
    "*.sqlite" \
    "*.sqlite3" \
    "logs/" \
    "runtime/" \
    "__pycache__/" \
    "node_modules/"
do

    grep -qxF \
        "$item" \
        .gitignore 2>/dev/null \
        || echo "$item" >> .gitignore

done

sort -u \
    .gitignore \
    -o .gitignore

git status --short

git add . \
    ':!.env' \
    ':!.env.*' \
    ':!*.db' \
    ':!*.sqlite' \
    ':!*.sqlite3' \
    ':!logs/' \
    ':!runtime/' \
    ':!__pycache__/' \
    ':!node_modules/'

git diff --cached --check

if git diff --cached --quiet; then

    echo \
    "COMMIT=NOTHING_TO_COMMIT"

else

    git commit \
        -m "chore: synchronize honeycomb control plane and engine inventory"

fi

if git remote get-url origin >/dev/null 2>&1; then

    branch="$(
        git branch --show-current
    )"

    git push \
        origin \
        "$branch"

    echo \
    "GITHUB_SYNC=PASS"

else

    echo \
    "GITHUB_SYNC=NO_ORIGIN"

fi
SH

chmod 700 scripts/sync_all.sh

cat > scripts/online.sh <<'SH'
#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="${HOME}/honeycomb-execution-core"
cd "$ROOT"

bash scripts/start_control_plane.sh

if command -v cloudflared >/dev/null 2>&1; then

    echo "PUBLIC_TUNNEL=STARTING"

    nohup cloudflared \
        tunnel \
        --url http://127.0.0.1:8787 \
        --no-autoupdate \
        > runtime/cloudflared.log 2>&1 &

    echo $! \
        > runtime/cloudflared.pid

    sleep 3

    grep -Eo \
        'https://[-a-zA-Z0-9]+\.trycloudflare\.com' \
        runtime/cloudflared.log \
        | tail -1 || true

else

    echo "CLOUDFLARED=NOT_INSTALLED"

fi

if command -v npx >/dev/null 2>&1; then

    echo \
    "VERCEL_PROJECT_DIR=$ROOT/dashboard"

    echo \
    "VERCEL_DEPLOY=npx vercel --prod"

fi
SH

chmod 700 scripts/online.sh

cat > .gitignore.tmp_honeycomb <<'EOF'
.env
.env.*
*.db
*.sqlite
*.sqlite3
logs/
runtime/
__pycache__/
node_modules/
EOF

cat .gitignore.tmp_honeycomb >> .gitignore
rm -f .gitignore.tmp_honeycomb

sort -u \
    .gitignore \
    -o .gitignore

echo
echo "=== INVENTORY ==="

python - <<'PY'
import json
from pathlib import Path

data = json.loads(
    Path(
        "runtime/inventory.json"
    ).read_text()
)

print(
    "SOURCE_FILES=",
    len(data["files"])
)

print(
    "ENGINE_CANDIDATES=",
    len(data["engines"])
)
PY

bash scripts/verify_control_plane.sh

git add \
    docs/superpowers/plans \
    orchestrator \
    dashboard \
    scripts \
    .gitignore

git diff --cached --check

git commit \
    -m "feat: add honeycomb production control plane" \
    || true

bash scripts/sync_all.sh || true

echo
echo "=== HONEYCOMB READY ==="
echo
echo "LOCAL_DASHBOARD=http://127.0.0.1:8787"
echo
echo "TESTNET:"
echo "bash ~/honeycomb-execution-core/scripts/start_testnet.sh"
echo
echo "ONLINE:"
echo "bash ~/honeycomb-execution-core/scripts/online.sh"
echo
echo "LIVE:"
echo "LIVE_ARMED=1 bash ~/honeycomb-execution-core/scripts/start_live.sh"
