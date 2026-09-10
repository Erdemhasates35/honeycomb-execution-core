#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot local repair for LiveKernel transport bootstrap.

Preserves the original kernel as a timestamped backup and performs only
additive/targeted substitutions. No trading logic is removed.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

root = Path(__file__).resolve().parent
path = root / "live" / "kernel.py"
if not path.exists():
    raise SystemExit(f"missing {path}")

src = path.read_text(encoding="utf-8")
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = path.with_name(f"kernel.py.pre_network_repair.{ts}")
backup.write_text(src, encoding="utf-8")

# 1) Stable per-user lock path; the old literal is retained in the backup.
src = src.replace(
    'self.path = path or "/tmp/honeycomb_sf.lock"',
    'self.path = path or os.path.join(os.path.expanduser("~"), ".honeycomb", "sf.lock")\n        os.makedirs(os.path.dirname(self.path), exist_ok=True)'
)

# 2) Import the shared guard + endpoint failover from the kernel itself.
# This does not depend on sitecustomize/PYTHONPATH startup behavior.
anchor = 'from typing import Any, Dict, List, Optional, Tuple\n'
boot = (
    anchor +
    '\n# HONEYCOMB NETWORK BOOT: guard + Binance multi-endpoint failover.\n'
    'try:\n'
    '    import honeycomb_execution_guard  # noqa: F401\n'
    '    import binance_endpoint_failover  # noqa: F401\n'
    'except Exception as _network_boot_exc:\n'
    '    if os.getenv("EXECUTION_MODE", "").upper() == "LIVE" and os.getenv("LIVE_ARMED", "0") == "1":\n'
    '        raise RuntimeError("HONEYCOMB LIVE NETWORK BOOT FAILED: %s" % _network_boot_exc) from _network_boot_exc\n'
)
if 'import binance_endpoint_failover  # noqa: F401' not in src:
    if anchor not in src:
        raise SystemExit("kernel import anchor not found; nothing changed")
    src = src.replace(anchor, boot, 1)

# 3) Do not let a previous transient public-network failure block time sync.
# Signed business calls still honor stale-halt; the time endpoint is the
# recovery mechanism and must remain reachable through endpoint failover.
old = 'if time.time() < self._stale_until:\n            raise RuntimeError("stale-halt active %.0fs" % (self._stale_until - time.time()))'
new = (
    'if time.time() < self._stale_until and signed and path != self.v["time"]:\n'
    '            raise RuntimeError("stale-halt active %.0fs" % (self._stale_until - time.time()))'
)
if old in src:
    src = src.replace(old, new, 1)

path.write_text(src, encoding="utf-8")
print(f"REPAIRED {path}")
print(f"BACKUP   {backup}")
