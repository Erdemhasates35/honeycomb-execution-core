#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Compatibility runner for the existing LOBSTER engine.

Keeps the original engine intact and raises its leverage floor to 40x while
preserving its 10-agent, 30+ indicator and microstructure implementation.
"""
from __future__ import annotations
import os, threading
import lobster_extreme_momentum_engine as base

base.MIN_LEV = max(40, int(float(os.getenv("MIN_LEVERAGE", "40"))))
base.MAX_LEV = max(base.MIN_LEV, int(float(os.getenv("MAX_LEVERAGE", "75"))))

if __name__ == "__main__":
    base.main()
