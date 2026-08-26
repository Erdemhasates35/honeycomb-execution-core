# Honeycomb Live Engines

Three production engines on a shared kernel. No ghost fills. No hardcoded prices.

| Engine | Venue | Port | Entry |
|--------|-------|------|-------|
| **APEX** | USDT-M (`fapi`) | 8091 | `python3 live/apex_usdt.py` |
| **HELIX** | COIN-M (`dapi`) | 8092 | `python3 live/helix_coin.py` |
| **MAKER SNIPER** | USDT or COIN (GTX) | 8093 | `python3 live/maker_sniper.py` |
| Desk | local control | 8788 | `python3 live/desk.py` |

## What this fixes

1. Ghost fills — stale FALLBACK no longer opens or closes
2. Mark vs fill — avgPrice + userTrades RP + commission
3. Exchange SL — STOP_MARKET / TAKE_PROFIT_MARKET closePosition
4. Multi-bot Cross bleed — single-flight flock
5. COIN-M signature — HELIX signs only against dapi
6. -1021 timestamp — server time sync + recvWindow 10s
7. Connection reset 104 — backoff, never treated as fill
8. Coin-flip sides — removed; EMA/RSI/ATR only
9. Maker edge — GTX post-only
10. Funding veto — skip when you would pay

## Honesty

These cut specific failure modes. They do **not** guarantee 10x returns.

## Termux

```bash
cd ~/honeycomb-execution-core
# EXECUTION_MODE=live LIVE_ARMED=1 AUTO_PAPER=0
# BINANCE_API_KEY=... BINANCE_SECRET=...
# MARGIN_TYPE=ISOLATED MAX_LEVERAGE=20

python3 live/apex_usdt.py
python3 live/helix_coin.py
python3 live/maker_sniper.py
python3 live/desk.py
```

Run one aggressive engine at a time on small capital.
