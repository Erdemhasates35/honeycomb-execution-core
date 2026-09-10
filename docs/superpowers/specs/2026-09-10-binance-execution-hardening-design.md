# Binance Execution Hardening Design — 2026-09-10

## 1. Evidence-driven diagnosis

The observed `HTTP 418 / -1003` is an IP-level rate-limit ban, not a normal order rejection. Binance documents `-1003` as TOO_MANY_REQUESTS and explicitly states that continued rate-limit violations can result in an IP ban and recommends WebSocket streams instead of polling. Binance also states that 429 requires backoff and that IP bans scale with repeat violations.

The observed `-2015` in the other engine is a separate authentication/permission/IP problem: Binance defines `-2015` as invalid API key, IP, or permissions. It must not be converted into a retry storm and must fail closed.

The observed `DÖNGÜ HATASI: 'allow'` is a Python contract failure: a caller is assuming a decision dictionary contains an `allow` key. The canonical `alpha_core.get_technical_decision()` already promises a dictionary and returns `allow` on its normal/error paths, so the parliament surface should still use defensive `.get()` access for compatibility with older engines.

The SQLite error is consistent with an unsafe environment path. The current Termux value is a comma-separated list of database names even though `engine_alpha2.py` treats it as one path. The first canonical path must be selected without deleting any of the existing database files.

## 2. Target architecture

```text
Signal / AI / Parliament / Alpha / Helix engines
                    |
                    v
        +-------------------------+
        | Honeycomb execution     |
        | guard (shared, additive) |
        +-------------------------+
          |                    |
     public market          signed/account
        data                     data
          |                    |
          v                    v
   Binance WS cache       Binance REST
          |                    |
          +---------+----------+
                    |
             LiveKernel / routers
                    |
              Binance orders
```

The guard is intentionally below the existing engines and above `urllib.request.urlopen`. This means old engines gain the rate/ban protection without being rewritten or having execution semantics removed.

## 3. Rate-limit design

A conservative shared IP budget is enforced across processes using an `fcntl`-protected state file. The default safety budget is 900 request-weight units per minute, substantially below the documented public API ceiling commonly exposed by Binance Futures environments. Order calls receive a separate short-window budget. The goal is not to maximize API utilization; it is to make accidental multi-engine polling incapable of escalating into a ban.

On HTTP 429 or 418, the guard persists the maximum of `Retry-After` and the parsed `banned until` timestamp. While the halt is active, local calls fail before reaching Binance. This is deliberately fail-closed and does not attempt to evade the ban by changing IPs or credentials.

## 4. WebSocket-first design

One shared market WebSocket connection subscribes to the configured symbols' `bookTicker`, `markPrice`, and kline streams for the timeframes used by the technical engines. The connection is bounded by Binance's stream limits and reconnects after disconnects/24-hour lifecycle boundaries.

Fresh WebSocket data is persisted to a small local SQLite cache. Public REST reads for book ticker, mark price, ticker price, kline, and exchangeInfo can then be served from actual Binance stream/bootstrap data without generating another Binance request. If the cache is unavailable or stale, the guard falls back to the original REST call through the rate gate.

This is not simulated data: every cached value originates from Binance market streams or a controlled Binance REST bootstrap.

## 5. Signed execution safety

The guard does not silently synthesize account balances, positions, order acknowledgements, or fills. Signed execution endpoints continue to use the existing HMAC logic. Unknown/failed account state remains a hard stop for new live entries.

The existing `LiveKernel` remains the execution authority. Existing `positionSide`, `reduceOnly`, exchange-filter, fill-resolution, TP/SL, and single-flight behavior are retained.

## 6. SQLite safety

The existing `LEARNING_DB_PATH` may contain a legacy comma-separated list. The additive startup layer normalizes it to the first canonical database target for engines that interpret the variable as a scalar path. Existing database files remain untouched. A direct engine edit is intentionally deferred unless runtime evidence shows it is still required after normalization.

## 7. Scientific basis

### Volatility targeting
Moreira & Muir (2017), *The Journal of Finance*, find that portfolios which reduce risk when volatility is high can improve Sharpe ratios and utility. The implementation therefore scales risk downward as ATR/volatility rises instead of treating leverage as constant.

### Liquidity and transaction cost
Amihud (2002), *Journal of Financial Markets*, documents a relation between illiquidity and returns and uses absolute return relative to dollar volume as an accessible illiquidity proxy. The system therefore treats spread, volume ratio, slippage and fees as first-class entry costs rather than assuming execution at the signal price.

### Time-series momentum
Moskowitz, Ooi & Pedersen (2012), *Journal of Financial Economics*, document time-series momentum across liquid futures markets. The architecture therefore keeps multi-horizon directional confirmation rather than relying on one short timeframe.

### Kelly sizing
Kelly (1956) provides the theoretical foundation for sizing exposure as a function of edge and payoff odds. The implementation uses fractional/guarded Kelly-like multipliers rather than full Kelly because estimation error and leverage make full Kelly inappropriate for an automated leveraged futures system.

These studies support risk-management principles; they do not establish profitability of this specific strategy.

## 8. Safety invariants

1. 418/429 causes local backoff, never request amplification.
2. API authentication failures do not retry indefinitely.
3. No order is generated from fallback/mock market data.
4. Unknown balance/position state blocks new LIVE entries.
5. Existing reduce-only and position-side semantics are preserved.
6. No API secret is printed by diagnostics.
7. Existing source files and database files are not deleted.

## 9. Verification

Required local gates:

```bash
python3 -m py_compile honeycomb_execution_guard.py sitecustomize.py sovereign_parliament_engine.py live/kernel.py
python3 -m pytest -q tests/test_execution_guard.py
python3 -c 'import sitecustomize; import honeycomb_execution_guard as g; print("GUARD", g._PATCHED)'
```

After the current Binance ban expires, signed diagnostics must verify server time, account balance and position state before any live order-path test. A Testnet order-path check is the first execution validation; LIVE is not used as a substitute for failed authentication or rate-limit verification.

## Official evidence

- Binance error codes: https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin/error-code
- Binance REST rate limits / 418 / 429: https://developers.binance.com/en/docs/products/spot/rest-api
- Binance Futures WebSocket market streams: https://developers.binance.com/en/docs/derivatives-trading-usds-futures/websocket-market-streams/Connect
- Binance USD-M user data streams: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-api/user-data-streams
- Binance signed endpoint timing: https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin-pro/general-info
- Moreira & Muir (2017): https://onlinelibrary.wiley.com/doi/10.1111/jofi.12513
- Amihud (2002): https://doi.org/10.1016/S1386-4181(01)00024-6
