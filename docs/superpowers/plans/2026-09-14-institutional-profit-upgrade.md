# Institutional Profit Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the existing Honeycomb engines around signed expected value, exact net-cost accounting, 5% margin budgeting, dynamic exits, live reconciliation and auditable portfolio analytics without deleting existing architecture.

**Architecture:** Existing engines remain signal specialists. `institutional_finance.py` is the deterministic financial contract; `profit_economics.py` adapts live Binance fees/funding; `risk_analytics.py` standardizes portfolio statistics; the LiveKernel remains the only order authority. AI/Parliament supplies contextual evidence but cannot bypass the deterministic financial gate.

**Tech Stack:** Python 3.11+, SQLite, Binance Futures REST/WebSocket, existing TypeScript engines, existing dashboard/control plane, GitHub Actions and Termux runtime.

**Spec:** `docs/INSTITUTIONAL_FINANCE_DESIGN_2026-09-14.md`

## Global Constraints

- Preserve all existing engine names, public interfaces, databases, logs and integrations.
- Do not delete production files, trade history, audit history or secrets.
- Default margin budget: 5% of available equity.
- Dynamic leverage target: 40x–75x, hard-capped by the actual exchange/symbol maximum.
- `EXECUTION_MODE=LIVE` and `LIVE_ARMED=1` remain the hard live gate.
- No mock fills or synthetic live-market evidence.
- A submitted order is not a fill until exchange status/executed quantity is reconciled.
- PnL must be available in quote currency and percentage of posted margin.
- Optimize on net expectancy, profit factor, net PnL and drawdown; never optimize on win rate alone.

---

### Task 1: Establish deterministic financial contract

**Files:**
- Create: `institutional_finance.py`
- Test: `tests/test_institutional_finance.py`

**Interfaces:**
- `directional_expected_move_bps(model_move_pct, confidence, atr_pct, side) -> float`
- `funding_cost_fraction(funding_rate, side, holding_seconds, next_funding_seconds, interval_seconds=28800) -> float`
- `net_edge_bps(expected_move_bps, maker_fee_rate, taker_fee_rate, spread_bps, slippage_bps, funding_bps, style, market_impact_bps=0, adverse_selection_bps=0) -> float`
- `pnl_percent(side, entry, exit, quantity, margin, fee_rate=0, funding=0) -> float`
- `position_size_from_risk(...) -> dict`
- `dynamic_exit_surface(...) -> dict`

- [x] Add tests for signed direction, funding settlement count, cost-aware edge, margin PnL percentage, sizing and dynamic exit direction.
- [x] Implement the deterministic functions with finite-value guards.
- [ ] Run `python3 -m pytest tests/test_institutional_finance.py -q` in the Termux checkout and record the result.

### Task 2: Replace ambiguous execution economics

**Files:**
- Modify: `profit_economics.py`
- Modify: `adaptive_profit_runtime.py`
- Test: `tests/test_institutional_finance.py`

**Interfaces:**
- Preserve `market_economics`, `net_edge`, `choose_style`, `choose_leverage`, `sizing`, `RuntimeConfig`, `PnLTracker`.

- [x] Remove absolute-value expected-return handling.
- [x] Make funding settlement-aware and signed.
- [x] Separate maker and taker spread/slippage assumptions.
- [x] Make maker selection depend on fill probability.
- [x] Make PnL funding semantics explicit: positive funding is a cost, negative funding is a credit.
- [ ] Run the finance test suite and Python compilation.

### Task 3: Upgrade quantitative signal planner

**Files:**
- Modify: `aggressive_profit_optimizer.py`
- Preserve: `alpha_core.py` public interfaces

**Interfaces:**
- Preserve `plan(symbol, kernel=None)` and `dynamic_trail(pos, mark)` return shapes while adding `expected_move_bps`.

- [x] Preserve MTF EMA/ADX/momentum evidence.
- [x] Convert the directional signal into signed expected move.
- [x] Gate entry on positive net edge after spread/slippage/commission.
- [x] Cap signal margin fraction at 5%.
- [x] Keep leverage within 40–75 before exchange-specific clamping.
- [ ] Add exchange-specific maximum leverage discovery through LiveKernel where available.
- [ ] Run optimizer unit tests with real deterministic candle fixtures from existing project tests only.

### Task 4: Upgrade Profit-Max execution engine

**Files:**
- Modify: `profit_max_engine.py`
- Modify: `risk_analytics.py`

**Interfaces:**
- Preserve `open_trade`, `manage`, `scan`, `main`.

- [ ] Replace TP-derived expected move with `expected_move_bps` from the quantitative planner.
- [ ] Use live commission rates and settlement-aware funding for every decision.
- [ ] Use 5% margin budget with separate stop-risk reporting.
- [ ] Calculate TP/SL from `dynamic_exit_surface` and current ATR/regime.
- [ ] Persist margin-return PnL, fee, funding, MAE, MFE, hold time and execution shortfall.
- [ ] Reconcile exchange positions on startup before accepting a new symbol.
- [ ] Reconcile order status before recording a fill.
- [ ] Preserve the live gate and no-order behavior when unarmed.
- [ ] Run deterministic DB schema tests and syntax checks.

### Task 5: Upgrade Extreme/Omega scanner

**Files:**
- Modify: `extreme_scanner_engine.py`
- Preserve: `extreme_scanner_omega.py`

**Interfaces:**
- Preserve `scan_symbol`, `check_closed_positions`, `main_loop`.

- [ ] Remove the `or 10` leverage fallback.
- [ ] Use central dynamic leverage and exchange maximum.
- [ ] Replace static universal TP/SL with ATR/regime/confidence exit surface.
- [ ] Add net-edge gate before `open_market`.
- [ ] Preserve audit ledger and exclude secrets from audit output.
- [ ] Reconcile `_open_meta` with exchange positions after restart.
- [ ] Record actual close PnL rather than zero-valued placeholder close PnL.
- [ ] Run scanner import/compile and dry gate checks with `LIVE_ARMED=0`.

### Task 6: Upgrade Lobster, Aggressive, Alpha and specialist engines

**Files:**
- Modify as needed: `lobster_extreme_momentum_engine.py`, `aggressive_profit_optimizer.py`, `alpha_core.py`, `long_sniper_hunter.py`, `aggressive_short_hunter.py`, `profit_aggressive_engine.py`, `profit_lobster_engine.py`, `profit_maker_sniper.py`

**Interfaces:**
- Preserve each engine's existing public entry points.

- [ ] Normalize outputs into the financial contract.
- [ ] Add microstructure evidence where already available: spread, book imbalance/microprice and volume/volatility regime.
- [ ] Prevent duplicate correlated-indicator weighting.
- [ ] Apply positive net-edge gate before execution.
- [ ] Apply 40–75 dynamic leverage subject to exchange limits.
- [ ] Apply dynamic exits and partial-profit/trailing logic without changing existing engine names.
- [ ] Add actual-fill PnL accounting.
- [ ] Compile every modified engine.

### Task 7: Upgrade Sovereign/Helix/Parliament authority

**Files:**
- Modify: `sovereign_parliament_engine.py`, `helix_sovereign_pro.py`, `ai_sovereign_engine.py`, related AI authority modules

**Interfaces:**
- Preserve existing agent/Parliament APIs.

- [ ] Treat AI outputs as contextual evidence and calibrated confidence, not direct order authority.
- [ ] Require deterministic data-validity, net-edge, risk and exchange gates before live order submission.
- [ ] Preserve all 25 agents and existing provider integrations where configured.
- [ ] Record model/provider confidence and decision provenance without secrets.
- [ ] Repair only confirmed syntax/import/merge defects; preserve valid inherited code.
- [ ] Compile/import all authority modules.

### Task 8: Central portfolio analytics and persistence

**Files:**
- Modify: `risk_analytics.py`
- Modify: engine-specific SQLite schemas only through additive `ALTER TABLE` columns
- Preserve: all existing `.db`, `.db-wal`, `.db-shm` history

**Interfaces:**
- `summarize_trades(rows, starting_equity=0) -> dict`

- [x] Standardize net PnL, win rate, profit factor, expectancy and drawdown.
- [x] Standardize fee/funding totals and MAE/MFE/holding time.
- [ ] Add margin-return percentage and implementation shortfall fields to live trade ledgers.
- [ ] Add portfolio-level concentration/exposure metrics.
- [ ] Ensure no history is deleted or rewritten.

### Task 9: Dashboard/control-plane observability

**Files:**
- Modify: `dashboard/index.html`, `orchestrator/control_plane.py`, `orchestrator/ui_control_plane.py`, registry/status adapters

**Interfaces:**
- Preserve current endpoints and panel ports.

- [ ] Expose actual balance, available margin, open notional, leverage, net PnL %, fees %, funding, drawdown %, profit factor and expectancy.
- [ ] Show order lifecycle: submitted, acknowledged, partially filled, filled, cancelled/rejected, protection confirmed.
- [ ] Show data freshness and financial-gate reasons for skipped trades.
- [ ] Never show or persist API secrets.
- [ ] Verify dashboard/control endpoints without placing new orders.

### Task 10: Static integrity and compatibility repair

**Files:**
- Existing repair/integrity scripts under `scripts/`
- All tracked Python/TypeScript files implicated by scans

- [ ] Scan all tracked files for conflict markers.
- [ ] Scan all ATR calls and ensure compatibility with existing `atr` interfaces.
- [ ] Scan numeric comparisons for `None`/NaN hazards.
- [ ] Compile Python modules and type-check TypeScript where configured.
- [ ] Run `git diff --check`.
- [ ] Preserve backups and historical artifacts.

### Task 11: Three-stage verification

**Stage 1:**
- [ ] Unit tests for finance mathematics.
- [ ] Exact known-value tests for fee/spread/slippage/funding/PnL.
- [ ] No-order invariant under `LIVE_ARMED=0`.

**Stage 2:**
- [ ] Engine integration/import tests.
- [ ] DB schema compatibility tests.
- [ ] Dashboard/control health checks.
- [ ] Reconciliation tests for restart and partial fills.

**Stage 3:**
- [ ] Termux live-gate run with `LIVE_ARMED=0` first.
- [ ] Only after all checks pass, user may independently arm live execution.
- [ ] Confirm real exchange order IDs/fill quantities/protection before claiming live execution.
- [ ] Publish a final audit containing measured results, not performance guarantees.

### Task 12: Evidence and academic report

**Files:**
- Create: `docs/INSTITUTIONAL_PROFIT_AUDIT_2026-09-14.md`
- Create/update: `docs/PROFIT_MAXIMIZATION_REVIEW_2026-09-12.md`

- [ ] Document claim → mechanism → model → metric → observed data → decision.
- [ ] Separate backtest, paper, replay and live evidence.
- [ ] Report net expectancy, profit factor, net PnL %, drawdown %, MAE/MFE, fees, funding and implementation shortfall.
- [ ] Explicitly avoid guaranteed-return claims.
- [ ] Preserve all previous evidence and append the new audit.
