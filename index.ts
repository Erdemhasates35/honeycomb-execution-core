import fs from "node:fs";
import path from "node:path";
import { ExecutionRouter } from "./execution/execution_router.js";

function loadEnv(): void {
  const envPath = path.resolve(process.cwd(), ".env");
  if (!fs.existsSync(envPath)) return;
  for (const raw of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    if (key && process.env[key] === undefined) process.env[key] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
  }
}

async function main(): Promise<void> {
  loadEnv();
  const router = new ExecutionRouter();
  let shuttingDown = false;
  const shutdown = async (): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    await router.terminate();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());
  await router.initialize();
  const snapshot = router.snapshot();
  process.stdout.write(JSON.stringify({
    status: "initialized",
    mode: router.mode,
    market: router.market,
    availableBalance: snapshot.balance,
    activePositions: snapshot.positions.length,
    reconciledFills: snapshot.fills.length,
  }) + "\n");
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "Execution initialization failed";
  process.stderr.write(JSON.stringify({ status: "failed", error: message }) + "\n");
  process.exitCode = 1;
});
