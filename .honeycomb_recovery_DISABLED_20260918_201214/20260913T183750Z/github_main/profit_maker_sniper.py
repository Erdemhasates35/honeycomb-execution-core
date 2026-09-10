#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""Compatibility runner for MAKER-SNIPER with a 40x minimum leverage policy."""
from __future__ import annotations
import threading
import live.maker_sniper as base

base.LEV = max(40, min(75, int(float(base.ENV.get("MAX_LEVERAGE", "75")))))

if __name__ == "__main__":
    threading.Thread(target=base.loop, daemon=True).start()
    base.run_flask()
