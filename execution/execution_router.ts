import { BinanceLiveExecutionAdapter } from "./binance_live_adapter.js";
import { NexusTelemetryClient } from "./nexus_telemetry_client.js";
import { PaperExecutionAdapter } from "./paper_execution_adapter.js";
import { TestExecutionAdapter } from "./test_execution_adapter.js";
import type { ExecutionAdapter, ExecutionMode, ExecutionSnapshot, FuturesMarket, Fill, OrderIntent } from "./types.js";

export interface RouterConfig {
  mode?: ExecutionMode;
  market?: FuturesMarket;
  initialBalance?: number;
  apiKey?: string;
  apiSecret?: string;
  testnet?: boolean;
  paperFeeRate?: number;
  paperSlippageBps?: number;
  telemetry?: NexusTelemetryClient;
  accountLabel?: string;
  strategyCode?: string;
  riskProfileCode?: string;
  executorId?: string;
  settlementAsset?: string;
  riskLimitsJson?: string;
  riskContextJson?: string;
}

export class ExecutionRouter implements ExecutionAdapter {
  readonly mode: ExecutionMode;
  readonly market: FuturesMarket;
  private readonly adapter: ExecutionAdapter;

  constructor(config: RouterConfig = {}) {
    this.mode = (config.mode ?? process.env.EXECUTION_MODE ?? "PAPER").toUpperCase() as ExecutionMode;
    this.market = (config.market ?? process.env.FUTURES_MARKET ?? "COIN_M").toUpperCase() as FuturesMarket;
    if (!["TEST","PAPER","TESTNET","LIVE"].includes(this.mode)) throw new Error(`Unsupported EXECUTION_MODE=${this.mode}`);
    if (!["COIN_M","USDT_M"].includes(this.market)) throw new Error(`Unsupported FUTURES_MARKET=${this.market}`);
    if (config.testnet === true && this.mode !== "TESTNET") throw new Error("testnet=true requires EXECUTION_MODE=TESTNET");

    if (this.mode === "TEST") {
      this.adapter = new TestExecutionAdapter({ market: this.market, initialBalance: config.initialBalance });
      return;
    }
    if (this.mode === "PAPER") {
      this.adapter = new PaperExecutionAdapter({ market: this.market, initialBalance: config.initialBalance, feeRate: config.paperFeeRate, slippageBps: config.paperSlippageBps });
      return;
    }

    const shared = {
      market: this.market,
      accountLabel: config.accountLabel,
      strategyCode: config.strategyCode,
      riskProfileCode: config.riskProfileCode,
      executorId: config.executorId,
      settlementAsset: config.settlementAsset,
      riskLimitsJson: config.riskLimitsJson,
      riskContextJson: config.riskContextJson,
    };

    if (this.mode === "TESTNET") {
      if (process.env.TESTNET_ARMED !== "1") throw new Error("TESTNET requires TESTNET_ARMED=1");
      const apiKey = config.apiKey ?? process.env.BINANCE_TESTNET_API_KEY ?? "";
      const apiSecret = config.apiSecret ?? process.env.BINANCE_TESTNET_API_SECRET ?? "";
      if (!apiKey || !apiSecret) throw new Error("TESTNET requires separate Binance testnet credentials");
      const telemetry = config.telemetry ?? NexusTelemetryClient.fromEnv();
      this.adapter = new BinanceLiveExecutionAdapter({ ...shared, telemetry, mode: "TESTNET", apiKey, apiSecret });
      return;
    }

    if (process.env.LIVE_ARMED !== "1") throw new Error("LIVE requires LIVE_ARMED=1");
    const apiKey = config.apiKey ?? process.env.BINANCE_API_KEY ?? "";
    const apiSecret = config.apiSecret ?? process.env.BINANCE_API_SECRET ?? process.env.BINANCE_SECRET ?? "";
    if (!apiKey || !apiSecret) throw new Error("LIVE requires Binance production credentials");
    if (!config.riskProfileCode && !process.env.NEXUS_RISK_PROFILE_CODE) throw new Error("LIVE requires an enabled NEXUS_RISK_PROFILE_CODE");
    if (!config.executorId && !process.env.NEXUS_EXECUTOR_ID) throw new Error("LIVE requires NEXUS_EXECUTOR_ID");
    const telemetry = config.telemetry ?? NexusTelemetryClient.fromEnv();
    this.adapter = new BinanceLiveExecutionAdapter({ ...shared, telemetry, mode: "LIVE", apiKey, apiSecret });
  }

  initialize(): Promise<void> { return this.adapter.initialize(); }
  place(intent: OrderIntent): Promise<Fill> { return this.adapter.place(intent); }
  close(symbol: string, referencePrice?: number, guardApprovalDigest?: string): Promise<Fill | null> { return this.adapter.close(symbol, referencePrice, guardApprovalDigest); }
  markPrice(symbol: string): Promise<number> { return this.adapter.markPrice(symbol); }
  snapshot(): ExecutionSnapshot { return this.adapter.snapshot(); }
  terminate(): Promise<void> { return this.adapter.terminate(); }
  get testAdapter(): TestExecutionAdapter | undefined { return this.adapter instanceof TestExecutionAdapter ? this.adapter : undefined; }
}
