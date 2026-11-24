import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { RiskStateStore } from "../execution/risk_state_store.js";

test("risk high-water mark survives restart and never decreases", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "honeycomb-risk-state-"));
  const filePath = path.join(directory, "risk-state.ndjson");
  try {
    const first = new RiskStateStore(filePath);
    assert.equal(await first.updatePeakEquity("account-1", 1000), 1000);
    assert.equal(await first.updatePeakEquity("account-1", 900), 1000);
    const restarted = new RiskStateStore(filePath);
    assert.equal(await restarted.loadPeakEquity("account-1"), 1000);
    assert.equal(await restarted.updatePeakEquity("account-1", 1250), 1250);
    assert.equal(await first.loadPeakEquity("account-1"), 1250);
    assert.equal((await readFile(filePath, "utf8")).trim().split("\n").length, 2);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("risk state journal fails closed on corrupt history", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "honeycomb-risk-state-corrupt-"));
  const filePath = path.join(directory, "risk-state.ndjson");
  try {
    const store = new RiskStateStore(filePath);
    await import("node:fs/promises").then(fs => fs.writeFile(filePath, "{bad-json}\n"));
    await assert.rejects(() => store.loadPeakEquity("account-1"), /corrupt/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
