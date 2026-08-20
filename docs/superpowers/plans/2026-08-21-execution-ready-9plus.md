# Honeycomb Execution-Ready 9+ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore deterministic runtime health, harden execution/risk boundaries, validate testnet execution end-to-end, and raise the Honeycomb core to a measurable 9+ quality gate without deleting or rewriting environment secrets.

**Architecture:** Keep the existing control-plane, engine, risk/router, and bridge boundaries. Make registry/state writes atomic and schema-valid, make status APIs failure-tolerant, strengthen typed validation/error boundaries/observability in the execution core, then certify the complete testnet path.

**Tech Stack:** Python 3.13, Go, TypeScript, Bash, SQLite, HTTP/JSON, existing Binance testnet bridge, existing deterministic quality gate.

**Spec:** Existing approved Honeycomb/Quantum Nexus execution-ready design from the conversation.

## Global Constraints

- Preserve `.env` and all existing secret values; never print, rotate, delete, or commit secrets.
- Preserve existing working engines and public endpoints unless a compatibility fix is required.
- Do not delete source files, databases, logs, or existing runtime artifacts.
- LIVE mode remains explicitly gated by the existing `LIVE_ARMED=1` control.
- Testnet/paper validation precedes any live execution claim.
- Every changed runtime path gets deterministic tests or an executable verification.
- Quality certification must be produced by the repository quality gate, not by manual scoring.

---

### Task 1: Harden Control Plane registry and status runtime

**Files:**
- Modify: `orchestrator/control_plane.py`
- Modify: `orchestrator/registry.json`
- Test: `tests/test_control_plane.py`

**Interfaces:**
- `inventory() -> dict[str, Any]` remains the inventory API.
- `current_status() -> dict[str, Any]` must return structured degraded telemetry instead of raising on registry corruption.
- Registry writes use temporary-file + replace semantics.

- [ ] Step 1: Add tests for empty registry, malformed registry, atomic recovery, and `/api/status` success.
- [ ] Step 2: Run the focused tests and verify they fail against the current implementation.
- [ ] Step 3: Implement schema-safe registry loading with a canonical default object and atomic writes; preserve existing keys.
- [ ] Step 4: Wrap quality/inventory failures into explicit status fields so one telemetry subsystem cannot crash `/api/status`.
- [ ] Step 5: Run focused tests and verify all pass.
- [ ] Step 6: Verify `.env` is never read into test output or persisted into repository artifacts.

### Task 2: Strengthen deterministic quality gate

**Files:**
- Modify: `orchestrator/quality_gate.py`
- Test: `tests/test_quality_gate.py`

**Interfaces:**
- `evaluate_file(path, root) -> dict[str, Any]` retains its output shape.
- `evaluate_repository(root) -> dict[str, Any]` retains `summary` and `files`.

- [ ] Step 1: Add tests for weighted core certification, syntax failures, missing tests, and debt markers.
- [ ] Step 2: Run the focused tests and record failures.
- [ ] Step 3: Replace heuristic-only core certification with explicit required checks while retaining backward-compatible report fields.
- [ ] Step 4: Make malformed source/config inputs fail closed in the report rather than silently receive passing defaults.
- [ ] Step 5: Run focused tests and regenerate `reports/quality-gate.json`.

### Task 3: Harden Go execution/risk core

**Files:**
- Modify: `cmd/engine/main.go`
- Modify: `internal/config/config.go`
- Modify: `internal/edge/calculator.go`
- Modify: `internal/order/router.go`
- Modify: `internal/order/types.go`
- Modify: `internal/risk/state.go`
- Test: existing Go tests plus focused tests under corresponding packages

**Interfaces:**
- Preserve existing exported types/functions and HTTP/runtime ports.
- Add explicit validation errors rather than panics or silent zero values.
- Add structured runtime logging around order decisions, risk transitions, and calculator failures.

- [ ] Step 1: Add failing tests for invalid configuration, invalid order quantities/prices, risk-state transitions, and calculator boundary conditions.
- [ ] Step 2: Run `go test ./...` and focused package tests to establish the failing baseline.
- [ ] Step 3: Implement typed validation and explicit error propagation at config, calculator, order, and risk boundaries.
- [ ] Step 4: Add structured observability without logging credentials or signed payloads.
- [ ] Step 5: Run `go test ./...` and static checks; require zero failures.

### Task 4: Harden Python/TypeScript execution engines

**Files:**
- Modify only execution-critical files that fail certification: `engine.py`, `engine_live.py`, `engine_scalp_tn.py`, `alpha_brain.py`, `auto_paper.py`, `master_alpha.py`, `quantum_sovereign_core.py`, `index.ts`, `verify.ts`, `verify2.ts`, `verify3.ts`
- Test: existing test suite plus focused engine validation tests

**Interfaces:**
- Preserve existing CLI entry points and environment variable names.
- Add type annotations, input validation, explicit error boundaries, and bounded observability.

- [ ] Step 1: Add failing tests for malformed configuration, invalid symbols/quantities, unavailable engine dependencies, and deterministic fallback behavior.
- [ ] Step 2: Run Python/TypeScript tests or compile checks and capture failures.
- [ ] Step 3: Implement minimal compatibility-preserving fixes.
- [ ] Step 4: Verify no `.env` or secret values are emitted by logs, reports, or tests.
- [ ] Step 5: Run the complete available test/compile suite.

### Task 5: Repair bridge testnet contract

**Files:**
- Modify: `nexus_testnet_bridge.py`
- Modify: `repair_and_testnet_order.sh`
- Test: bridge/API tests

**Interfaces:**
- Preserve `:8100`, `/health`, `/status`, `/testnet/order`, `/testnet/open-orders`, `/testnet/positions`.
- Keep authentication and request validation deterministic.

- [ ] Step 1: Add tests for valid/invalid order payloads and authenticated account endpoints.
- [ ] Step 2: Reproduce the current 400/401 behavior with local tests.
- [ ] Step 3: Fix request schema normalization and authentication configuration without changing secret values.
- [ ] Step 4: Run bridge tests and verify health/status remain 200.
- [ ] Step 5: Execute one bounded testnet order flow and verify resulting telemetry.

### Task 6: End-to-end execution certification

**Files:**
- Modify: `run_nexus_testnet.sh`
- Modify: `runtime/start_testnet.sh`
- Modify: `diagnose_honeycomb.sh`
- Test: end-to-end runtime verification

- [ ] Step 1: Start control plane, engine, and bridge using existing launchers.
- [ ] Step 2: Verify ports `8787`, `8000`, and `8100` and all health/status endpoints.
- [ ] Step 3: Verify `/api/status` remains healthy across repeated inventory/quality calls.
- [ ] Step 4: Execute the existing testnet order workflow and verify authentication, order response, and telemetry.
- [ ] Step 5: Run the repository quality gate and require `core_9plus=true`.
- [ ] Step 6: Verify Git working tree contains only intentional changes and no environment/secret files.

### Task 7: Final certification

**Files:**
- Generated: `reports/quality-gate.json`
- Generated/updated: runtime inventory and telemetry artifacts as already defined by the repository

- [ ] Step 1: Run the full test suite.
- [ ] Step 2: Run quality certification.
- [ ] Step 3: Run runtime health verification.
- [ ] Step 4: Run final secret/environment integrity checks without exposing values.
- [ ] Step 5: Commit the implementation branch with a deterministic release message.
- [ ] Step 6: Open a pull request to `main` only after all gates pass.
