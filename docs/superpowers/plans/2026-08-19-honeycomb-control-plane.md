# Honeycomb Control Plane Implementation Plan

**Goal:** Existing Honeycomb engines become one modular control plane supporting TESTNET, PAPER and LIVE modes with browser telemetry and GitHub synchronization.

**Architecture:** Existing engines remain execution modules. A control plane sits above them, inventories them, monitors ports/processes/logs/databases, exposes browser telemetry, and starts only the selected existing execution launcher.

**Tech Stack:** Bash, Python standard library, SQLite, Node.js, TypeScript, Git, optional Vercel and Cloudflare Tunnel.

**Global Constraints**
- Preserve existing source and historical engines.
- Never print API secrets.
- Keep .env, databases, logs and runtime state outside Git.
- Support TESTNET, PAPER and LIVE.
- Existing ports 8000 and 8100 remain untouched.
- Control plane uses port 8787.
- LIVE requires explicit LIVE_ARMED=1.
