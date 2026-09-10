#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ten-pass numeric + import + syntax guards."""
from __future__ import annotations
import math
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAILS = []

def ok(name, cond, detail=""):
    if cond:
        print("PASS", name)
    else:
        print("FAIL", name, detail)
        FAILS.append(name)

def run_once(i):
    from live.kernel import _finite_num, _gt, _lt, _ge, _le, ema, rsi
    import live
    import alpha_core
    ok("finite_none", _finite_num(None) == 0.0)
    ok("finite_nan", _finite_num(float("nan")) == 0.0)
    ok("finite_valid", _finite_num(12.5) == 12.5)
    ok("gt_none", _gt(None, 10) is False)
    ok("gt_valid", _gt(12, 10) is True)
    ok("lt_valid", _lt(8, 10) is True)
    ok("ge_valid", _ge(10, 10) is True)
    ok("le_valid", _le(9, 10) is True)
    ok("live_has_live_order_fn", hasattr(live, "live_order_fn"))
    ok("live_has_circuit", hasattr(live, "CircuitBreaker"))
    ok("live_has_trail", hasattr(live, "DynamicTrailingStopEngine"))
    ok("live_has_partial", hasattr(live, "PartialProfitEngine"))
    ok("alpha_has_klines", hasattr(alpha_core, "klines") and callable(alpha_core.klines))
    ok("alpha_has_get_technical_decision", hasattr(alpha_core, "get_technical_decision"))
    ok("alpha_has_DEFENSE_ENABLED", hasattr(alpha_core, "DEFENSE_ENABLED"))
    ok("alpha_has_extreme_quality", hasattr(alpha_core, "extreme_quality"))
    k = alpha_core.kelly_fraction(0.55, 1.2, 1.0)
    ok("kelly_bounded", 0.0 <= k <= 0.25, str(k))
    vs = alpha_core.volatility_target_size(0.08)
    ok("vol_target_bounded", alpha_core.MIN_RISK_PCT <= vs <= alpha_core.MAX_RISK_PCT, str(vs))
    eq = alpha_core.extreme_quality({"rsi": 18, "stoch": 10, "williams_r": -85, "cci": -120, "mfi": 12, "bb_position": 0.02, "ema_fast": 1, "ema_slow": 1.01, "adx": 30}, 80)
    ok("extreme_quality_dict", isinstance(eq, dict) and "quality" in eq)
    td = alpha_core.get_technical_decision("NOEXISTUSDT")
    ok("get_technical_decision_dict", isinstance(td, dict) and "allow" in td and "side" in td)
    ok("regime_kill_death", alpha_core.regime_kill_switch("DEATH", 0.01) is True)
    ok("corr_block_8", alpha_core.correlation_blocked("AAAUSDT", "LONG", [("X%dUSDT"%n, "LONG") for n in range(8)]) is True)
    series = [float(x) for x in range(1, 50)]
    ok("ema_runs", ema(series, 9) is not None)
    ok("rsi_runs", rsi(series, 14) is not None)
    ev = alpha_core.cost_aware_ev(80, 90, 0.12)
    ok("ev_finite", math.isfinite(ev))
    plan = alpha_core.partial_scale_plan(90, 0.1)
    ok("scale_plan", isinstance(plan, list) and len(plan) >= 1)
    ok("notional_band_reject_zero_eq", alpha_core.notional_band_check(10, 0, 0) is False)
    ok("liq_filter_tight_spread", alpha_core.liquidity_filter(3.0, 1.1, 0.08) is True)

if __name__ == "__main__":
    for i in range(10):
        print("===== PASS %d/10 =====" % (i + 1))
        try:
            run_once(i)
        except Exception:
            traceback.print_exc()
            FAILS.append("pass_%d_exception" % (i + 1))
    print("FAILS", FAILS)
    sys.exit(1 if FAILS else 0)
