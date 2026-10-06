#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
α-Agent 04 — Real ACK Latency Filter
Academic: Market microstructure latency literature (Hasbrouck, Cartea et al.)
Measures real order submit → exchange ACK time.
Rejects entries when observed latency exceeds hard threshold.
Zero cost, pure edge protection.
"""
from __future__ import annotations
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Any, Optional, Tuple

STATE_PATH = Path(os.getenv("HONEYCOMB_RUNTIME", ".honeycomb_runtime")) / "ack_latency_state.json"
MAX_SAMPLES = 200
HARD_LATENCY_MS = float(os.getenv("ACK_HARD_LATENCY_MS", "45.0"))   # reject above this
SOFT_LATENCY_MS = float(os.getenv("ACK_SOFT_LATENCY_MS", "22.0"))   # size reduction zone
WINDOW_SEC = 300  # 5 min rolling

def _load() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"samples": [], "updated_at": 0.0}

def _save(st: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    st["updated_at"] = time.time()
    # keep only last MAX_SAMPLES
    st["samples"] = st["samples"][-MAX_SAMPLES:]
    STATE_PATH.write_text(json.dumps(st))

def record_ack(submit_ts: float, ack_ts: float, symbol: str = "", side: str = "") -> float:
    """
    Call immediately after exchange ACK received.
    Returns latency in milliseconds.
    """
    latency_ms = max(0.0, (ack_ts - submit_ts) * 1000.0)
    st = _load()
    st["samples"].append({
        "ts": ack_ts,
        "latency_ms": round(latency_ms, 3),
        "symbol": symbol,
        "side": side,
    })
    _save(st)
    return latency_ms

def current_latency_stats() -> Dict[str, float]:
    st = _load()
    now = time.time()
    recent = [s["latency_ms"] for s in st["samples"] if now - s["ts"] <= WINDOW_SEC]
    if not recent:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "n": 0, "mean": 0.0}
    recent.sort()
    n = len(recent)
    def pct(p: float) -> float:
        idx = min(n - 1, int(n * p))
        return recent[idx]
    return {
        "p50": round(pct(0.50), 2),
        "p90": round(pct(0.90), 2),
        "p99": round(pct(0.99), 2),
        "n": n,
        "mean": round(sum(recent) / n, 2),
    }

def latency_gate() -> Tuple[bool, str, Dict[str, float]]:
    """
    Returns (allowed: bool, reason: str, stats)
    allowed=False → REJECT new entry.
    """
    stats = current_latency_stats()
    if stats["n"] < 5:
        return True, "INSUFFICIENT_SAMPLES", stats
    if stats["p90"] >= HARD_LATENCY_MS:
        return False, f"P90_LATENCY_{stats['p90']}ms", stats
    if stats["p50"] >= SOFT_LATENCY_MS:
        return True, f"SOFT_HIGH_{stats['p50']}ms", stats  # allow but caller should reduce size
    return True, "OK", stats

# Self-test
if __name__ == "__main__":
    t0 = time.time()
    time.sleep(0.012)
    lat = record_ack(t0, time.time(), "BTCUSDT", "LONG")
    assert lat > 0
    allowed, reason, stats = latency_gate()
    print("PASS", allowed, reason, stats)
