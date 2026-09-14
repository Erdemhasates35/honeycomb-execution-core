"""Compatibility runner for the existing LOBSTER engine.

Preserves the original 10-agent/microstructure engine while enforcing the
central 5% margin budget and 40x–75x requested leverage range.
"""
from __future__ import annotations
import os
import lobster_extreme_momentum_engine as base

base.MIN_LEV=max(40,int(float(os.getenv("MIN_LEVERAGE","40"))))
base.MAX_LEV=max(base.MIN_LEV,int(float(os.getenv("MAX_LEVERAGE","75"))))
if hasattr(base,"RISK_FRACTION"):
    base.RISK_FRACTION=min(.05,max(0.0,float(base.RISK_FRACTION)))
if hasattr(base,"RISK_PCT"):
    base.RISK_PCT=min(.05,max(0.0,float(base.RISK_PCT)))

if __name__=="__main__":base.main()
