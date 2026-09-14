# Compatibility runner for AGG-LIVE with centralized 40x–75x leverage bounds.
from __future__ import annotations
import os
import aggressive_live_engine as base

_original_plan = base.plan

def plan(symbol, kernel=None):
    p = _original_plan(symbol, kernel)
    if p:
        requested = int(float(p.get("leverage", os.getenv("MIN_LEVERAGE", "40"))))
        lo = max(40, int(float(os.getenv("MIN_LEVERAGE", "40"))))
        hi = max(lo, int(float(os.getenv("MAX_LEVERAGE", "75"))))
        p["leverage"] = max(lo, min(hi, requested))
        p["risk_pct"] = min(0.05, max(0.0, float(p.get("risk_pct", 0.05))))
    return p

base.plan = plan
base.MAX_POS = int(float(base.ENV.get("MAX_POSITIONS", base.MAX_POS)))

if __name__ == "__main__":
    base.main()
