# COIN-M TEST/PAPER Router v10 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a non-destructive execution-mode layer supporting TEST, PAPER, COIN_M and USDT_M while preserving the existing LIVE engine path.

**Architecture:** Signal/strategy logic remains upstream. A thin execution router selects TEST, PAPER, or LIVE and a venue adapter selects COIN_M or USDT_M. TEST is deterministic/offline; PAPER uses public market data and simulated fills; LIVE delegates to the existing Binance engine with the selected market type.

**Tech Stack:** TypeScript, Node.js, existing Binance engine, native fetch, Node test runner.

**Spec:** User-approved 2026-08-25 Nexus/Honeycomb COIN-M-first execution-mode upgrade.

## Global Constraints

- Preserve existing files and behavior unless a compatibility-preserving extension is required.
- Do not delete or overwrite the user's `.env`.
- Add missing environment variables idempotently.
- LIVE remains a separate execution path and requires `LIVE_ARMED=1`.
- Default new router venue is `COIN_M`; USDT_M remains supported.
- TEST must never contact Binance private endpoints.
- PAPER must never submit private orders.

---

### Task 1: Venue-aware Binance adapter

**Files:**
- Modify: `BinanceFuturesEngineCatE.ts`
- Test: `tests/binance-venue.test.ts`

Add `marketType: 'COIN_M' | 'USDT_M'` with backward-compatible default `USDT_M`. Map REST/WebSocket paths by venue while keeping existing USDT-M behavior unchanged.

### Task 2: Deterministic TEST adapter

**Files:**
- Create: `execution/test_execution_adapter.ts`
- Test: `tests/execution-test-adapter.test.ts`

Implement deterministic order acceptance, fills, position accounting, PnL, and event telemetry with no network access.

### Task 3: Market-connected PAPER adapter

**Files:**
- Create: `execution/paper_execution_adapter.ts`
- Test: `tests/paper-execution-adapter.test.ts`

Use public market-data endpoints only. Apply exchange metadata, tick/step/contract-size normalization, simulated fees/slippage, deterministic fill policy, and position/PnL journaling.

### Task 4: Unified router

**Files:**
- Create: `execution/execution_router.ts`
- Create: `execution/types.ts`
- Test: `tests/execution-router.test.ts`

Route TEST/PAPER/LIVE without duplicating strategy code. Require `LIVE_ARMED=1` for LIVE. Default venue `COIN_M` for the new router.

### Task 5: Nexus entrypoint and environment contract

**Files:**
- Create: `nexus_execution_entry.ts`
- Modify: `.env.example`
- Modify: `package.json`

Add explicit `EXECUTION_MODE`, `FUTURES_MARKET`, paper parameters, and npm scripts. Do not alter or remove existing environment variables.

### Task 6: Remove credential fallback from the executable entrypoint

**Files:**
- Modify: `index.ts`

Remove embedded credential fallback values and require environment configuration, while preserving the existing LIVE initialization flow and event handling.

### Task 7: Verification

Run TypeScript compilation, unit tests, and a static check proving TEST/PAPER contain no private-order calls. Create a PR from the feature branch; do not merge automatically.
