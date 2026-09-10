# Runtime fixes — 2026-08-23

- Binance signed requests now synchronize against `/fapi/v1/time`, use a 10s receive window, refresh every 5 minutes, and recover once from Binance `-1021` timestamp errors.
- Termux TESTNET and UI launchers load only valid shell-style `KEY=VALUE` entries from `.env`; annotation lines no longer execute as commands.
- `scripts/normalize_env.sh` preserves a timestamped backup and removes invalid `.env` lines.
- Live execution remains backend-controlled; these changes do not enable live trading.
