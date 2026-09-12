# Honeycomb — Profit Maximization Review — 2026-09-12

## Objective function

Primary objective: maximize expected **net trading return**. Secondary objective: minimize avoidable transaction cost and negative expectancy. The model is:

`NetEdge = ExpectedGrossMove - Commission - Spread - Slippage - FundingCost + FundingCredit`

The execution policy therefore chooses maker/taker style, leverage and entry threshold jointly rather than optimizing any one variable in isolation.

## Evidence-backed design

1. Binance exposes user-specific USD-M commission rates through `GET /fapi/v1/commissionRate`; the engine should prefer those live rates over hard-coded fee assumptions.
2. Binance supports RPI and documents maker/post-only behavior; the engine can evaluate liquidity-adding execution when expected fill probability justifies the opportunity cost.
3. Binance moved USD-M conditional orders to the Algo Order API. TP/SL logic must therefore use `/fapi/v1/algoOrder` rather than the legacy conditional order types on `/fapi/v1/order`.
4. Binance exposes leverage and max-notional information through futures account/exchange interfaces. Leverage must be constrained by the actual symbol bracket; `40x` is the strategy floor, not a promise that every symbol supports 40x.
5. Optimal-execution research shows that execution price, volume and market impact must be optimized dynamically rather than treated as fixed constants. Almgren-Chriss-style execution models formalize the trade-off between execution cost and price uncertainty; volume-dependent extensions make the execution policy adaptive to liquidity.

## Engine architecture

### L1 — Market perception
- bookTicker / spread
- mark price
- funding
- volume and volatility
- MTF technical state

### L2 — Alpha synthesis
- alpha_core
- extreme scanner
- aggressive momentum engines
- Sovereign/Helix parliament
- historical outcomes stored in SQLite

### L3 — Economic execution
- live commission rate
- maker/taker decision
- spread/slippage estimate
- funding carry
- leverage selection
- minimum economically viable expected move
- exchange filters and notional sizing

## Database integration

Existing SQLite databases are treated as historical evidence, not synthetic training data. Compatible trade/outcome tables can provide symbol/side/regime priors, fee history, realized PnL and execution quality. The integration must be read-compatible first; no database rows are deleted or rewritten merely for optimization.

## Current defects identified

- `helix_sovereign_pro.py` in the current main tree contains a missing `Dict` import and uses `ROOT` before defining it.
- Its default leverage range is still 10–25 in the current file, inconsistent with the new 40–75 policy.
- Its OpenRouter fallback strings contain concatenated model identifiers instead of valid model slugs.
- Its entry failure branch contains duplicated logging and an exception variable referenced outside an exception scope.
- The live kernel still contains a legacy `place_protect` implementation; the protection bridge patches this surface, so both surfaces must be kept contract-compatible.
- The live gate shows intermittent DNS failures for open Algo Order queries and account-balance inconsistencies; this is an operational data-path problem, not an alpha signal.
- The reported `LiveKernel üzerinde kullanılabilir emir fonksiyonu bulunamadı` message is inconsistent with the current GitHub Helix path, which calls `kernel.open_market`; therefore the local Termux checkout is not identical to current `main` and must be synchronized before further diagnosis.

## Expected improvement areas

- Dynamic maker/taker routing can reduce avoidable round-trip commission and spread cost when fill probability is sufficient.
- Funding-aware direction selection can turn negative funding carry into an explicit cost/credit term rather than ignoring it.
- Dynamic leverage should increase only when confidence and expected net edge rise; leverage itself does not create alpha.
- Partial-profit and trailing modules can convert favorable excursions into realized net PnL while preserving participation in larger moves.
- Historical DB priors can suppress repeated low-expectancy symbol/regime combinations and increase capital allocation to historically stronger conditions.

## Important limitation

No academic result can justify a guaranteed profit increase in live markets. The correct empirical claim is an improvement in the objective function and measured out-of-sample expectancy, profit factor, net PnL after fees and execution cost. Live performance must be measured from actual fills, actual commissions and actual funding rather than simulated assumptions.
