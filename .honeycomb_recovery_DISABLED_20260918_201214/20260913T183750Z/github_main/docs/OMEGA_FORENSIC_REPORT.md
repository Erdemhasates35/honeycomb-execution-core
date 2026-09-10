# Honeycomb Omega Forensic Report — 2026-09-08

Nothing was deleted. Surfaces were completed and existing logic kept.

## Termux crash map (from live logs)

| Error | Root cause | Fix |
|---|---|---|
| `module 'alpha_core' has no attribute 'get_technical_decision'` | `alpha_core.py` missing on GitHub / truncated local copy | Added `get_technical_decision` + aliases |
| `module 'alpha_core' has no attribute 'DEFENSE_ENABLED'` | constant never exported | `DEFENSE_ENABLED` flag |
| `name 'klines' is not defined` | `detect_regime` called klines without defining it | `alpha_core.klines` returns OHLCV dict |
| `ImportError: cannot import name live_order_fn` | `live/__init__.py` imported names not in `kernel.py` | appended engines/indicators |
| `SyntaxError` at `extreme_quality` | truncated cat EOF on Termux | rewritten complete function |
| `latin-1 codec can't encode` | UTF-8 logs on latin-1 stdout | `sys.stdout.reconfigure(utf-8, replace)` |
| `sqlite3.OperationalError: unable to open database` | missing parent dir | `ensure_db()` + `/tmp` fallback |
| `extreme_scanner_omega.py` not found | filename drift | alias module + engine |
| Binance `-1003 Too many requests` | no kline cache | 12s TTL cache |
| Circular `live` ↔ `alpha_core` | `__init__` imported alpha_core | `__init__` only re-exports kernel |

## Academic profit stack

1. Kelly (Thorp 1969) — fractional Kelly cap 25%
2. Volatility targeting (Moreira & Muir 2017)
3. Time-series momentum (Moskowitz, Ooi, Pedersen 2012)
4. Cost-aware EV (fees + slippage + funding)
5. Wilder ATR trailing (1978)
6. Triple-barrier scale-out (López de Prado)
7. Liquidity/spread filter (Amihud analogue)
8. Regime kill-switch
9. Correlation/concentration shield
10. Expectancy anti-martingale risk multiplier

## Tests

`python3 tests/test_omega_guards.py` — 10 consecutive passes, 28 assertions each.
