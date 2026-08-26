# Honeycomb Live Engines

Three production engines on a shared dual-venue HMAC kernel.

| Engine | Venue | Port | Command |
|--------|-------|------|---------|
| APEX | USDT-M fapi | 8091 | `python3 live/apex_usdt.py` |
| HELIX | COIN-M dapi | 8092 | `python3 live/helix_coin.py` |
| MAKER SNIPER | GTX post-only | 8093 | `python3 live/maker_sniper.py` |
| Desk | local control | 8788 | `python3 live/desk.py` |

## Critical: kernel

`live/kernel.py` may ship as a loader. Full implementation is dual-venue HMAC with:
fill ledger (avgPrice + userTrades RP), exchange STOP/TP, stale-book halt, token bucket,
single-flight flock, funding veto, slip reject, GTX.

If `import live.kernel` fails, place the full `kernel.py` from the release artifact
or run the write helper when published.

## Fixes vs your forensic week

1. No ghost fills (no FALLBACK prices)
2. Fill-accurate RP from userTrades
3. Exchange-resident SL/TP
4. Cross-engine single-flight lock
5. COIN-M signs only dapi (no fapi signature on USD_PERP)
6. Time sync + recvWindow (kill -1021)
7. Conn reset 104 backoff (never treated as fill)
8. Coin-flip sides removed
9. Maker GTX fee path
10. Funding-window veto

## Honesty

These cut the failure modes behind ~-2.47 USDT week and Cross 50x liquidations.
They do **not** guarantee 10x. Prefer ISOLATED + MAX_LEVERAGE<=20 on small capital.
One aggressive engine at a time.

## Termux

```bash
cd ~/honeycomb-execution-core
git pull origin main
# .env: EXECUTION_MODE=live LIVE_ARMED=1 AUTO_PAPER=0
# BINANCE_API_KEY=... BINANCE_SECRET=...
# MARGIN_TYPE=ISOLATED MAX_LEVERAGE=20

python3 live/apex_usdt.py
```
