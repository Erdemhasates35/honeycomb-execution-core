# config.py
import os
import sys
from typing import Dict

from execution_economics import normalize_legacy_fee_rate


def load_env(path: str) -> Dict[str, str]:
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().split("#")[0].strip()
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


def _required_positive(cfg: Dict, key: str, default: float):
    value = _parse_float(cfg.get(key, default), default)
    if value is None or value <= 0:
        print(f"KRITIK: {key} must be > 0")
        sys.exit(1)
    return value


def validate_startup(env_path: str = None) -> Dict:
    path = env_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ENV = load_env(path)

    cfg = {}
    mode = ENV.get("EXECUTION_MODE", "paper").strip().lower()
    if mode not in ("live", "testnet", "paper", "simulation"):
        print("Kritik: EXECUTION_MODE geçersiz. Beklenen: live|testnet|paper|simulation")
        sys.exit(1)
    cfg["MODE"] = mode

    cfg["BINANCE_API_KEY"] = ENV.get("BINANCE_API_KEY") or ENV.get("API_KEY")
    cfg["BINANCE_SECRET"] = ENV.get("BINANCE_SECRET") or ENV.get("BINANCE_API_SECRET") or ENV.get("BINANCE_SECRET_KEY")
    cfg["BINANCE_BASE_URL"] = ENV.get("BINANCE_BASE_URL", "https://fapi.binance.com").strip()

    if cfg["MODE"] == "live":
        if not cfg["BINANCE_API_KEY"] or not cfg["BINANCE_SECRET"]:
            print("KRITIK: LIVE mod için Binance API anahtarlari yok")
            sys.exit(1)
        lower = cfg["BINANCE_BASE_URL"].lower()
        if "testnet" in lower or "sandbox" in lower or "localhost" in lower:
            print("KRITIK: LIVE modu ancak gercek production endpoint ile calisabilir. BASE_URL: %s" % cfg["BINANCE_BASE_URL"])
            sys.exit(1)
        for f in ("SIMULATION", "PAPER", "DRY_RUN"):
            if ENV.get(f) and ENV.get(f).lower() in ("1", "true", "yes"):
                print(f"KRITIK: {f} etkin. LIVE baslatilamaz.")
                sys.exit(1)

    cfg["MAX_LEVERAGE"] = _parse_int(ENV.get("MAX_LEVERAGE", "20"), 20)
    if not isinstance(cfg["MAX_LEVERAGE"], int) or cfg["MAX_LEVERAGE"] < 1 or cfg["MAX_LEVERAGE"] > 50:
        print("KRITIK: MAX_LEVERAGE must be integer between 1 and 50")
        sys.exit(1)

    cfg["LIVE_MAX_CAPITAL_PERCENT"] = _parse_float(ENV.get("LIVE_MAX_CAPITAL_PERCENT", "10"), 10.0)
    if cfg["LIVE_MAX_CAPITAL_PERCENT"] is None or cfg["LIVE_MAX_CAPITAL_PERCENT"] <= 0 or cfg["LIVE_MAX_CAPITAL_PERCENT"] > 100:
        print("KRITIK: LIVE_MAX_CAPITAL_PERCENT must be between 0 and 100")
        sys.exit(1)

    cfg["HTTP_PORT"] = _parse_int(ENV.get("HTTP_PORT", ENV.get("PORT", "8080")), 8080)
    cfg["AUTO_INTERVAL_SEC"] = _parse_int(ENV.get("AUTO_INTERVAL_SEC", "4"), 4)

    # Explicit fee contract: bps, never ambiguous percentages.
    legacy_fee = ENV.get("FEE_RATE")
    if ENV.get("MAKER_FEE_BPS") is not None:
        cfg["MAKER_FEE_BPS"] = _parse_float(ENV.get("MAKER_FEE_BPS"), 2.0)
    elif legacy_fee is not None:
        cfg["MAKER_FEE_BPS"] = normalize_legacy_fee_rate(legacy_fee) * 10000
    else:
        cfg["MAKER_FEE_BPS"] = 2.0

    if ENV.get("TAKER_FEE_BPS") is not None:
        cfg["TAKER_FEE_BPS"] = _parse_float(ENV.get("TAKER_FEE_BPS"), 5.0)
    elif legacy_fee is not None:
        cfg["TAKER_FEE_BPS"] = normalize_legacy_fee_rate(legacy_fee) * 10000
    else:
        cfg["TAKER_FEE_BPS"] = 5.0

    for key in ("MAKER_FEE_BPS", "TAKER_FEE_BPS"):
        if cfg[key] is None or cfg[key] < 0 or cfg[key] > 100:
            print(f"KRITIK: {key} must be between 0 and 100 bps")
            sys.exit(1)

    cfg["SLIPPAGE_BPS"] = max(0.0, _parse_float(ENV.get("SLIPPAGE_BPS", "1.0"), 1.0))
    cfg["SPREAD_BPS"] = max(0.0, _parse_float(ENV.get("SPREAD_BPS", "0.5"), 0.5))
    cfg["FUNDING_BUFFER_BPS"] = max(0.0, _parse_float(ENV.get("FUNDING_BUFFER_BPS", "1.0"), 1.0))
    cfg["OTHER_COST_BPS"] = max(0.0, _parse_float(ENV.get("OTHER_COST_BPS", "0.0"), 0.0))
    cfg["RISK_PER_TRADE_PCT"] = _required_positive(ENV, "RISK_PER_TRADE_PCT", 0.75)
    cfg["MAX_DAILY_LOSS_PCT"] = _required_positive(ENV, "MAX_DAILY_LOSS_PCT", 3.0)
    cfg["MAX_POSITION_SIZE_USDT"] = _required_positive(ENV, "MAX_POSITION_SIZE_USDT", 200.0)
    cfg["MIN_NET_EDGE_PCT"] = _required_positive(ENV, "MIN_NET_EDGE_PCT", 0.15)
    cfg["ADVERSE_BUFFER_PCT"] = max(0.0, _parse_float(ENV.get("ADVERSE_BUFFER_PCT", "0.10"), 0.10))

    # Backward-compatible decimal fee for legacy modules. New modules must use bps.
    cfg["FEE_RATE"] = float(cfg["TAKER_FEE_BPS"]) / 10000.0
    cfg["TP_M"] = _parse_float(ENV.get("TP_M", "16.0"), 16.0)
    cfg["SL_P"] = _parse_float(ENV.get("SL_P", "0.55"), 0.55)
    cfg["HOLD_MAX"] = _parse_int(ENV.get("HOLD_MAX", "10"), 10)
    cfg["CIRCUIT_BREAKER_THRESHOLD"] = _parse_int(ENV.get("CIRCUIT_BREAKER_THRESHOLD", "3"), 3)
    cfg["CIRCUIT_BREAKER_COOLDOWN_SEC"] = _parse_int(ENV.get("CIRCUIT_BREAKER_COOLDOWN_SEC", "15"), 15)
    cfg["_ENV_RAW"] = ENV
    return cfg
