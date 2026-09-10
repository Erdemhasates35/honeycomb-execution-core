# Binance Execution Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate Binance REST-rate-limit amplification, harden live execution fail-closed behavior, repair SQLite path normalization, and provide a shared WebSocket-first market-data layer without deleting existing engines or order logic.

**Architecture:** Additive cross-process guard loaded automatically by `sitecustomize.py`. The guard persists IP-ban/backoff state, enforces a conservative shared request budget across all Python engines, and serves public market data from a single Binance Futures WebSocket cache when fresh. Existing signed order/account calls remain REST-backed and fail closed; existing kernels, position-side semantics, reduce-only logic, AI/parliament logic, and learning databases are preserved.

**Tech Stack:** Python 3, stdlib `urllib`, `sqlite3`, `fcntl`, `threading`; `websocket-client` when available; existing Binance Futures REST/WebSocket APIs.

**Spec:** `docs/superpowers/specs/2026-09-10-binance-execution-hardening-design.md`

## Global Constraints

- Never delete existing production code, database files, backups, or order semantics.
- Never bypass Binance IP bans; honor `Retry-After`/ban-until and stop local REST traffic during the ban.
- No mock market data; WebSocket cache contains only Binance stream data.
- LIVE order creation remains fail-closed when authentication, timing, rate state, or exchange state is unknown.
- Preserve `positionSide="BOTH"` / reduce-only compatibility.
- Do not print API secrets.
- Every production behavior change gets a failing test before implementation.

### Task 1: Guard regression tests

**Files:**
- Create: `tests/test_execution_guard.py`

- [ ] **Step 1: Write failing tests** for ban parsing, Retry-After parsing, endpoint weights, order classification, and malformed `LEARNING_DB_PATH` normalization.
- [ ] **Step 2: Run:** `python3 -m pytest -q tests/test_execution_guard.py`
- [ ] **Step 3: Expected:** FAIL because the guard module does not yet exist.
- [ ] **Step 4: Commit:** `test: add execution guard regression coverage`

### Task 2: Cross-process Binance guard and WS-first market cache

**Files:**
- Create: `honeycomb_execution_guard.py`
- Create: `sitecustomize.py`

**Interfaces:**
- Produces: `parse_retry_after`, `parse_ban_until`, `BinanceRateGate`, `cache_public`, `cache_seed_public`, `start_ws`, `install`.
- Behavior: all Binance `urllib.request.urlopen` calls pass through one IP-wide rate gate; public ticker/mark/kline/exchangeInfo reads use the live WS cache when fresh; 418/429 state is persisted and honored.

- [ ] **Step 1:** Implement only enough guard behavior to satisfy Task 1.
- [ ] **Step 2:** Run `python3 -m pytest -q tests/test_execution_guard.py` and require PASS.
- [ ] **Step 3:** Add WS cache persistence and public-response interception.
- [ ] **Step 4:** Run syntax/import tests: `python3 -m py_compile honeycomb_execution_guard.py sitecustomize.py`.
- [ ] **Step 5:** Commit: `feat: add cross-process Binance rate guard and WS market cache`

### Task 3: Parliament compatibility hardening

**Files:**
- Modify: `sovereign_parliament_engine.py`

**Interfaces:**
- Preserve the existing engine entry point.
- Make the technical-decision contract tolerant of missing/legacy keys using `.get()` and fail closed.
- Keep `CircuitBreaker`, but ensure rate-ban errors do not cause a tight polling loop.

- [ ] **Step 1:** Add a regression test covering a technical-decision dictionary without `allow`.
- [ ] **Step 2:** Run the test and observe failure against the old access pattern.
- [ ] **Step 3:** Add the compatibility wrapper without removing the original implementation.
- [ ] **Step 4:** Run syntax and unit tests.
- [ ] **Step 5:** Commit: `fix: harden parliament decision contract`

### Task 4: SQLite path safety

**Files:**
- Covered additively by `sitecustomize.py` for existing engines; no database is deleted or moved.
- Optional follow-up: `engine_alpha2.py` only after local test evidence confirms a direct edit is necessary.

- [ ] **Step 1:** Test a comma-separated `LEARNING_DB_PATH` value and verify normalization to the first canonical path.
- [ ] **Step 2:** Run `python3 engine_alpha2.py` only after the Binance guard is active and the current IP ban is expired; verify `db_init()` no longer raises `unable to open database file`.

### Task 5: Live validation gate

**Files:**
- Create: `scripts/termux_execution_hardening.sh`

- [ ] **Step 1:** Add timestamped backups before any local mutation.
- [ ] **Step 2:** Install the additive guard files through heredocs.
- [ ] **Step 3:** Run py_compile and guard tests.
- [ ] **Step 4:** Verify environment names only with secrets redacted.
- [ ] **Step 5:** Verify REST gate state and WebSocket cache status without placing an order.
- [ ] **Step 6:** Verify signed balance/time/position reads after the ban expires.
- [ ] **Step 7:** Only after auth and state checks pass, enable a Testnet order-path validation; LIVE remains explicitly armed and fail-closed.

## Verification Gate

Success means: no uncontrolled Binance polling during a 418/429 ban; public market reads are WS-first when cache data is fresh; all Python engines share one conservative IP budget; SQLite initialization uses a valid canonical path; parliament never crashes because a decision key is missing; `live/kernel.py` remains syntactically valid; and no existing production file is deleted.