import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";

test("Node Binance guard fails closed on a non-finite request-weight limit", () => {
  const result = spawnSync(
    process.execPath,
    ["--import", "./honeycomb_node_guard.mjs", "-e", "process.stdout.write('guard-loaded')"],
    {
      cwd: process.cwd(),
      encoding: "utf8",
      env: { ...process.env, BINANCE_SAFE_WEIGHT_PER_MIN: "NaN", BINANCE_SAFE_ORDERS_PER_10S: "60" },
    },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /BINANCE_SAFE_WEIGHT_PER_MIN must be a finite positive number/);
});

test("Node Binance guard fails closed on a non-positive order limit", () => {
  const result = spawnSync(
    process.execPath,
    ["--import", "./honeycomb_node_guard.mjs", "-e", "process.stdout.write('guard-loaded')"],
    {
      cwd: process.cwd(),
      encoding: "utf8",
      env: { ...process.env, BINANCE_SAFE_WEIGHT_PER_MIN: "900", BINANCE_SAFE_ORDERS_PER_10S: "0" },
    },
  );

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /BINANCE_SAFE_ORDERS_PER_10S must be a finite positive number/);
});
