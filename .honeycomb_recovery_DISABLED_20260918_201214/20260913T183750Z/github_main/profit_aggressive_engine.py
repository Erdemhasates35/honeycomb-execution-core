#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Compatibility runner for AGG-LIVE with a 40x minimum leverage floor."""
from __future__ import annotations
import aggressive_live_engine as base

_original_plan = base.plan

def plan(symbol, kernel=None):
    p = _original_plan(symbol, kernel)
    if p:
        p['leverage'] = max(40, int(p.get('leverage', 40)))
    return p

base.plan = plan
base.MAX_POS = int(float(base.ENV.get("MAX_POSITIONS", base.MAX_POS)))

if __name__ == "__main__":
    base.main()
