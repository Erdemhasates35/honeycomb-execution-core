# config.py
import os
import sys
import json
from typing import Dict


def load_env(path: str) -> Dict[str, str]:
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().split("#")[0].strip()
    # overlay with os.environ
    for k, v in os.environ.items():
        env.setdefault(k, v)
    return env


def _parse_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default


def _parse_float(v, default=None):
    try:
        return float(v)
    except Exception:
        return default


def validate_startup(env_path: str = None) -> Dict:
    path = env_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ENV = load_env(path)

    cfg = {}
    mode = ENV.get("EXECUTION_MODE", "paper").strip().lower()
    if mode not in ("live", "testnet", "paper", "simulation"):
        print("Kritik: EXECUTION_MODE geçersiz. Beklenen: live|testnet|paper|simulation")
        sys.exit(1)
    cfg["MODE"] = mode

    # Binance
    cfg["BINANCE_API_KEY"] = ENV.get("BINANCE_API_KEY") or ENV.get("API_KEY")
    cfg["BINANCE_SECRET"] = ENV.get("BINANCE_SECRET") or ENV.get("BINANCE_API_SECRET") or ENV.get("BINANCE_SECRET_KEY")
    cfg["BINANCE_BASE_URL"] = ENV.get("BINANCE_BASE_URL", "https://fapi.binance.com").strip()

    # Global guards
    if cfg["MODE"] == "live":
        # Secrets must exist
        if not cfg["BINANCE_API_KEY"] or not cfg["BINANCE_SECRET"]:
            print("KRITIK: LIVE mod için Binance API anahtarlari yok")
            sys.exit(1)
        # Ensure base url is not testnet/sandbox
        lower = cfg["BINANCE_BASE_URL"].lower()
        if "testnet" in lower or "sandbox" in lower or "localhost" in lower:
            print("KRITIK: LIVE modu ancak gercek production endpoint ile calisabilir. BASE_URL: %s" % cfg["BINANCE_BASE_URL"])
            sys.exit(1)
        # prevent mock/paper flags
        for f in ("SIMULATION", "PAPER", "DRY_RUN", "AUTO_PAPER"):
            if ENV.get(f) and ENV.get(f).lower() in ("1", "true", "yes"):
                print(f"KRITIK: {f} etkin. LIVE baslatilamaz.")
                sys.exit(1)

    # Limits
    cfg["MAX_LEVERAGE"] = _parse_int(ENV.get("MAX_LEVERAGE", "50"), 50)
    if not isinstance(cfg["MAX_LEVERAGE"], int) or cfg["MAX_LEVERAGE"] < 1 or cfg["MAX_LEVERAGE"] > 50:
        print("KRITIK: MAX_LEVERAGE must be integer between 1 and 50")
        sys.exit(1)

    cfg["LIVE_MAX_CAPITAL_PERCENT"] = _parse_float(ENV.get("LIVE_MAX_CAPITAL_PERCENT", "10"), 10.0)
    if cfg["LIVE_MAX_CAPITAL_PERCENT"] is None or cfg["LIVE_MAX_CAPITAL_PERCENT"] <= 0 or cfg["LIVE_MAX_CAPITAL_PERCENT"] > 100:
        print("KRITIK: LIVE_MAX_CAPITAL_PERCENT must be between 0 and 100")
        sys.exit(1)

    # Port and runtime
    cfg["HTTP_PORT"] = _parse_int(ENV.get("HTTP_PORT", ENV.get("PORT", "8080")), 8080)
    cfg["AUTO_INTERVAL_SEC"] = _parse_int(ENV.get("AUTO_INTERVAL_SEC", "4"), 4)

    # Defaults that other modules expect
    cfg["FEE_RATE"] = _parse_float(ENV.get("FEE_RATE", ENV.get("FEE_RATE", "0.0004")), 0.0004)
    cfg["TP_M"] = _parse_float(ENV.get("TP_M", "16.0"), 16.0)
    cfg["SL_P"] = _parse_float(ENV.get("SL_P", "0.55"), 0.55)
    cfg["HOLD_MAX"] = _parse_int(ENV.get("HOLD_MAX", "10"), 10)
    cfg["MAX_POSITION_SIZE_USDT"] = _parse_float(ENV.get("MAX_POSITION_SIZE_USDT", "350"), 350.0)
    cfg["CIRCUIT_BREAKER_THRESHOLD"] = _parse_int(ENV.get("CIRCUIT_BREAKER_THRESHOLD", "3"), 3)
    cfg["CIRCUIT_BREAKER_COOLDOWN_SEC"] = _parse_int(ENV.get("CIRCUIT_BREAKER_COOLDOWN_SEC", "15"), 15)

    # Expose raw ENV if needed
    cfg["_ENV_RAW"] = ENV

    return cfg
