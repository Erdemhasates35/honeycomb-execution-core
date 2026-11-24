import { open, mkdir, readFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";

interface RiskStateRecord {
  accountId: string;
  peakEquity: number;
  updatedAt: string;
}

export class RiskStateStore {
  readonly filePath: string;

  constructor(filePath = process.env.NEXUS_RISK_STATE_PATH ?? path.join(homedir(), ".local", "state", "honeycomb", "risk-state.ndjson")) {
    const expanded = filePath === "~" ? homedir() : filePath.startsWith("~/") ? path.join(homedir(), filePath.slice(2)) : filePath;
    this.filePath = path.resolve(expanded);
  }

  async loadPeakEquity(accountId: string): Promise<number> {
    if (!accountId) throw new Error("Risk state account ID is required");
    let contents = "";
    try {
      contents = await readFile(this.filePath, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return 0;
      throw error;
    }
    let peak = 0;
    for (const [index, line] of contents.split("\n").entries()) {
      if (!line.trim()) continue;
      let record: RiskStateRecord;
      try {
        record = JSON.parse(line) as RiskStateRecord;
      } catch {
        throw new Error("Risk state journal is corrupt at line " + (index + 1));
      }
      if (!record.accountId || !Number.isFinite(record.peakEquity) || record.peakEquity <= 0 || !Number.isFinite(Date.parse(record.updatedAt))) {
        throw new Error("Risk state journal contains an invalid record at line " + (index + 1));
      }
      if (record.accountId === accountId) peak = Math.max(peak, record.peakEquity);
    }
    return peak;
  }

  async updatePeakEquity(accountId: string, equity: number): Promise<number> {
    if (!accountId || !Number.isFinite(equity) || equity <= 0) throw new Error("Risk state update requires a valid account and positive equity");
    const current = await this.loadPeakEquity(accountId);
    const next = Math.max(current, equity);
    if (next > current) {
      await mkdir(path.dirname(this.filePath), { recursive: true });
      const file = await open(this.filePath, "a", 0o600);
      try {
        await file.writeFile(JSON.stringify({ accountId, peakEquity: next, updatedAt: new Date().toISOString() }) + "\n");
        await file.sync();
      } finally {
        await file.close();
      }
    }
    return next;
  }
}
