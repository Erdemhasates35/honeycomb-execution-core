#!/data/data/com.termux/files/usr/bin/bash
# Helix kilit + ölü OpenRouter slug + ATR imzası. Termux'ta depo kökünden çalıştır.
set -euo pipefail
ROOT="${1:-$HOME/honeycomb-execution-core}"
cd "$ROOT"
git merge --abort 2>/dev/null || true
mkdir -p "$HOME/.honeycomb"
touch "$HOME/.honeycomb/sf.lock"

python3 - << 'PY'
import os, pathlib, re
root = pathlib.Path(".").resolve()
lock = os.path.expanduser("~/.honeycomb/sf.lock")

k = root / "live" / "kernel.py"
if k.exists():
    t = k.read_text(encoding="utf-8")
    n = t.replace('path or "/tmp/honeycomb_sf.lock"',
                  'path or os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock")')
    n = n.replace("/tmp/honeycomb_sf.lock", lock)
    if 'os.makedirs(os.path.dirname(self.path)' not in n:
        n = n.replace(
            'self.fd = open(self.path, "w")',
            'os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)\n        self.fd = open(self.path, "w")',
        )
    if "HONEYCOMB_LOCK_PATH" not in n:
        n = n.replace(
            "self.flock = SingleFlight()",
            'self.flock = SingleFlight(self.env.get("HONEYCOMB_LOCK_PATH") or os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock"))',
        )
    old = """def atr(closes, period=14):
    if len(closes) < period + 1: return None
    trs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    return sum(trs[-period:]) / period"""
    new = """def atr(closes=None, period=14, high=None, low=None, close=None, **_):
    series = close if close is not None else closes
    if series is None:
        return None
    if high is not None and low is not None and len(series) >= period + 1:
        trs = []
        prev = series[0]
        for i in range(1, len(series)):
            h = high[i] if i < len(high) else series[i]
            l = low[i] if i < len(low) else series[i]
            trs.append(max(h - l, abs(h - prev), abs(l - prev)))
            prev = series[i]
        return sum(trs[-period:]) / period
    if len(series) < period + 1:
        return None
    trs = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    return sum(trs[-period:]) / period"""
    if old in n:
        n = n.replace(old, new)
    if n != t:
        k.write_text(n, encoding="utf-8")
        print("ok live/kernel.py")
    else:
        print("skip live/kernel.py")

repls = [
    ("meta-llama/llama-3.1-8b-instruct:free", "nvidia/nemotron-3.5-lightning:free"),
    ("google/gemma-2-9b-it:free", "google/gemma-4-31b-it:free"),
    ("mistralai/mistral-7b-instruct:free", "minimax/minimax-m2.7:free"),
    ("huggingfaceh4/zephyr-7b-beta:free", "openrouter/free"),
    ("meta-llama/llama-3.1-70b-instruct:free", "openrouter/free"),
    ("llama-3.1-8b-instruct:free", "nvidia/nemotron-3.5-lightning:free"),
    ("gemma-2-9b-it:free", "google/gemma-4-31b-it:free"),
    ("mistral-7b-instruct:free", "minimax/minimax-m2.7:free"),
    ("zephyr-7b-beta:free", "openrouter/free"),
]
for p in list(root.glob("*.py")) + list(root.glob("live/*.py")):
    t = p.read_text(encoding="utf-8", errors="ignore")
    n = t
    for a, b in repls:
        n = n.replace(a, b)
    n = re.sub(
        r'"model": ENV.get\("OR_MODEL_FIN1"\) or "[^"]+"',
        '"model": ENV.get("OR_MODEL_FIN1") or "nvidia/nemotron-3.5-lightning:free"',
        n,
    )
    n = re.sub(
        r'"model": ENV.get\("OR_MODEL_FIN2"\) or "[^"]+"',
        '"model": ENV.get("OR_MODEL_FIN2") or "google/gemma-4-31b-it:free"',
        n,
    )
    n = re.sub(
        r'"model": ENV.get\("OR_MODEL_GEN1"\) or "[^"]+"',
        '"model": ENV.get("OR_MODEL_GEN1") or "minimax/minimax-m2.7:free"',
        n,
    )
    n = re.sub(
        r'"model": ENV.get\("OR_MODEL_GEN2"\) or "[^"]+"',
        '"model": ENV.get("OR_MODEL_GEN2") or "openrouter/free"',
        n,
    )
    if n != t:
        p.write_text(n, encoding="utf-8")
        print("ok", p.name)

envp = root / ".env"
if envp.exists():
    e = envp.read_text(encoding="utf-8")
    adds = {
        "HONEYCOMB_LOCK_PATH": lock,
        "OPENROUTER_MODEL": "openrouter/free",
        "OR_MODEL_FIN1": "nvidia/nemotron-3.5-lightning:free",
        "OR_MODEL_FIN2": "google/gemma-4-31b-it:free",
        "OR_MODEL_GEN1": "minimax/minimax-m2.7:free",
        "OR_MODEL_GEN2": "openrouter/free",
    }
    for key, val in adds.items():
        if re.search(r"^%s=" % re.escape(key), e, re.M):
            e = re.sub(r"^%s=.*$" % re.escape(key), "%s=%s" % (key, val), e, flags=re.M)
        else:
            e += "\n%s=%s\n" % (key, val)
    envp.write_text(e, encoding="utf-8")
    print("ok .env")
print("DONE")
PY

python3 -m py_compile live/kernel.py 2>/dev/null && echo "kernel compile ok" || echo "kernel compile skip"
echo "sonra: pkill -f helix_sovereign_pro.py; python3 helix_sovereign_pro.py"
