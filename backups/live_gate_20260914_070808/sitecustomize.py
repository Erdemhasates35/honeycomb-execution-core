# Honeycomb additive runtime hook.
# Python's site module imports sitecustomize automatically when this repo is on sys.path.
# Existing engines remain intact; shared guard and endpoint failover are installed additively.
import os

try:
    import honeycomb_execution_guard  # noqa: F401
    import binance_endpoint_failover  # noqa: F401
except Exception as _exc:
    _live = (os.getenv("EXECUTION_MODE", "").upper() == "LIVE" or
             os.getenv("HONEYCOMB_MODE", "").upper() == "LIVE")
    _armed = os.getenv("LIVE_ARMED", "0") == "1"
    if _live and _armed:
        raise RuntimeError("HONEYCOMB LIVE FAIL-CLOSED: network guard boot failed: %s" % _exc) from _exc
    print("[HONEYCOMB-GUARD] boot warning: %s" % _exc, flush=True)
