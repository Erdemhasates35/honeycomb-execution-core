# Honeycomb Deep Inventory — 2026-10-03

## Scope
Original repositories only:
- honeycomb-execution-core
- honeycomb-omega-x
- honeycomb_al

No files or history were deleted.

## Verified findings

### honeycomb-execution-core
1. **Multiple active-looking copies of core engines**
   - `live/kernel.py`: 46,239 bytes
   - `accounts/live/kernel.py`: 42,842 bytes
   - `accounts/COIN-1/live/kernel.py`: 39,006 bytes
   - `accounts/USDT-1/live/kernel.py`: 42,842 bytes
   - These are different blobs; they are not safe to treat as interchangeable.
2. **Alpha Core duplication**
   - root `alpha_core.py`: 20,434 bytes
   - `accounts/alpha_core.py`: 25,418 bytes
   - `accounts/COIN-1/alpha_core.py`: 20,434 bytes
   - `live/alpha_core.py`: 16,484 bytes
3. **AI Parliament duplication**
   - root and `live/` copies are identical blobs in the inspected pair.
   - `accounts/ai_parliament.py` is a different 26,593-byte implementation.
4. **Recovery/backup duplication is extensive**
   - The repository contains disabled recovery trees and many dated backups containing repeated engine files.
   - These must remain preserved under the no-deletion rule, but they must not be imported/executed as production sources.
5. **Go build blockers**
   - `go.mod` was missing from the inspected main tree.
   - `cmd/engine/main.go` contained a malformed `o s.Exit(1)`.
   - `internal/order/router.go` had a mutex re-entry deadlock path in `Close()`.
   - These were patched on branch `production-integrity-hardening`.
6. **Architecture mismatch**
   - README describes a real Go execution core, but the repository also contains Python/TypeScript engines and multiple execution paths.
   - `internal/order/router.go` currently uses fixed edge inputs rather than live order-book economics. This is not sufficient for a production PnL decision engine.
7. **CI quality problem**
   - The enhanced workflow contains explicitly named “Financial Error Simulation Tests” and a synthetic “Order Latency Benchmark”.
   - These do not prove exchange execution correctness and should not be treated as production financial validation.
8. **Test coverage gap**
   - Existing TypeScript coverage includes a paper adapter test using a stubbed fetcher.
   - This is useful for deterministic accounting/unit checks, but it is not a real exchange integration test.

### honeycomb-omega-x
- Repository is extremely small (GitHub metadata size: 26 KB).
- README defines a control-plane concept, but no indexed `package.json`, workflow, Next/Vite app source, or application test suite was found.
- Current state is therefore a specification/shell, not a verified production control plane.

### honeycomb_al
- This is a large App Builder workspace, not the same execution-core runtime.
- It contains generated Vercel output under `.vercel/output` and duplicated Honeycomb Python assets under `public/honeycomb` and `.vercel/output/static/honeycomb`.
- Source-of-truth and generated-output separation must be enforced; generated copies must never become an alternate production engine.

## 1000 TL accounting rule

A truthful realized PnL cannot be produced from the repository code alone. No verified exchange-testnet trade ledger was available through the connected GitHub interface, and inventing a trade series would violate the no-mock/no-fabrication requirement.

For every engine, the authoritative calculation must be:

**Net PnL = realized gross PnL − entry/exit fees − funding − slippage/implementation shortfall − other measured execution costs**

**Return % = Net PnL / starting equity × 100**

For a 1,000 TL starting equity, the report must use the actual recorded fills and actual costs. A fabricated “profit” number is explicitly rejected.

## Required production target
1. One canonical implementation per production engine.
2. Backups/recovery trees remain immutable evidence, never runtime imports.
3. Real exchange-testnet integration tests for authenticated order lifecycle.
4. Read-only public-market tests for price, book, exchangeInfo and funding.
5. Exact contract-aware PnL for USDT-M and COIN-M separately.
6. Fees/funding/slippage must come from observed exchange/testnet results, not fixed placeholders.
7. 1,000 TL report generated only from an auditable fill ledger.
8. LIVE mode remains fail-closed until testnet and accounting gates pass.
