import { randomUUID } from "node:crypto";
import { BinanceFuturesEngineCatE, type BinanceExchangeSymbol, type BinanceOrderStatus, type BinanceUserTrade, type OrderRequest } from "../BinanceFuturesEngineCatE.js";
import { reconcileBinanceUserTrades } from "./binance_fill.js";
import { NexusTelemetryClient, type NexusExecutionConfig } from "./nexus_telemetry_client.js";
import { RiskEngine, parseRiskLimits, type RiskContext } from "./risk_engine.js";
import { RiskStateStore } from "./risk_state_store.js";
import type { ExecutionAdapter, ExecutionMode, ExecutionSnapshot, Fill, FuturesMarket, OrderIntent, Position } from "./types.js";

interface BalanceRow {
  asset: string;
  balance?: string;
  walletBalance?: string;
  availableBalance?: string;
  withdrawAvailable?: string;
}

interface ProtectionRef {
  symbol: string;
  intentId: string;
  instrumentId: string;
  role: string;
  siblingOrderId: number;
  quantity: number;
  intent: OrderIntent;
}

interface RiskContextOverrides {
  peakEquity?: number;
  dailyRealizedPnl?: number;
  openOrders?: number;
  portfolioNotional?: number;
  estimatedSlippageBps?: number;
  estimatedFeeBps?: number;
  estimatedFundingBps?: number;
}

export interface BinanceLiveAdapterOptions {
  mode: "TESTNET" | "LIVE";
  market: FuturesMarket;
  apiKey: string;
  apiSecret: string;
  telemetry?: NexusTelemetryClient;
  accountLabel?: string;
  strategyCode?: string;
  riskProfileCode?: string;
  executorId?: string;
  settlementAsset?: string;
  riskLimitsJson?: string;
  riskContextJson?: string;
  estimatedSlippageBps?: number;
  estimatedFeeBps?: number;
  estimatedFundingBps?: number;
  fetcher?: typeof fetch;
}

export class BinanceLiveExecutionAdapter implements ExecutionAdapter {
  readonly mode: "TESTNET" | "LIVE";
  readonly market: FuturesMarket;
  private readonly engine: BinanceFuturesEngineCatE;
  private readonly telemetry: NexusTelemetryClient;
  private readonly accountLabel: string;
  private readonly strategyCode: string;
  private readonly riskProfileCode?: string;
  private readonly executorId?: string;
  private readonly settlementAsset: string;
  private riskEngine!: RiskEngine;
  private executionConfig?: NexusExecutionConfig;
  private readonly riskContextOverrides: RiskContextOverrides;
  private readonly riskStateStore: RiskStateStore;
  private equityUsd = Number.NaN;
  private availableBalanceUsd = Number.NaN;
  private peakEquityUsd = Number.NaN;
  private dailyRealizedPnlUsd = Number.NaN;
  private openOrderCount = Number.NaN;
  private lastDailyPnlRefreshAt = 0;
  private readonly estimatedSlippageBps: number;
  private readonly estimatedFeeBps: number;
  private readonly estimatedFundingBps: number;
  private readonly fills: Fill[] = [];
  private readonly instrumentIds = new Map<string,string>();
  private readonly contractSizes = new Map<string,number>();
  private readonly instrumentSettlementAssets = new Map<string,string>();
  private readonly protectionOrders = new Map<string,ProtectionRef>();
  private readonly orderUpdateHandler = (event: Record<string,unknown>) => { void this.handleProtectionUpdate(event); };
  private accountId = "";
  private initialized = false;
  private hedgeMode = false;
  private lastIncomeSyncTime = Date.now() - 7 * 24 * 60 * 60 * 1000;
  private balance = 0;
  private positions: Position[] = [];

  constructor(options: BinanceLiveAdapterOptions) {
    this.mode = options.mode;
    this.market = options.market;
    this.telemetry = options.telemetry ?? NexusTelemetryClient.fromEnv();
    this.accountLabel = options.accountLabel ?? process.env.NEXUS_ACCOUNT_LABEL ?? "";
    this.strategyCode = options.strategyCode ?? process.env.NEXUS_STRATEGY_CODE ?? "";
    this.riskProfileCode = options.riskProfileCode ?? process.env.NEXUS_RISK_PROFILE_CODE;
    this.executorId = options.executorId ?? process.env.NEXUS_EXECUTOR_ID;
    this.settlementAsset = options.settlementAsset ?? process.env.NEXUS_SETTLEMENT_ASSET ?? (this.market === "USDT_M" ? "USDT" : "");
    if (!this.accountLabel) throw new Error("NEXUS_ACCOUNT_LABEL is required");
    if (!this.strategyCode) throw new Error("NEXUS_STRATEGY_CODE is required");
    if (!this.settlementAsset) throw new Error("NEXUS_SETTLEMENT_ASSET is required for COIN_M");
    if (!this.riskProfileCode) throw new Error("NEXUS_RISK_PROFILE_CODE is required for TESTNET and LIVE");
    if (this.mode === "LIVE" && !this.executorId) throw new Error("LIVE requires NEXUS_EXECUTOR_ID");
    const riskContextJson = options.riskContextJson ?? process.env.NEXUS_RISK_CONTEXT_JSON;
    try {
      this.riskContextOverrides = riskContextJson ? JSON.parse(riskContextJson) as RiskContextOverrides : {};
      for (const [key,value] of Object.entries(this.riskContextOverrides)) {
        if (value !== undefined && (typeof value !== "number" || !Number.isFinite(value))) throw new Error("NEXUS_RISK_CONTEXT_JSON contains an invalid numeric override: " + key);
      }
    } catch (error) {
      if (error instanceof Error && error.message.startsWith("NEXUS_RISK_CONTEXT_JSON")) throw error;
      throw new Error("NEXUS_RISK_CONTEXT_JSON is invalid JSON");
    }
    this.riskStateStore = new RiskStateStore();
    this.estimatedSlippageBps = options.estimatedSlippageBps ?? Number(process.env.NEXUS_ESTIMATED_SLIPPAGE_BPS ?? "5");
    this.estimatedFeeBps = options.estimatedFeeBps ?? Number(process.env.NEXUS_ESTIMATED_FEE_BPS ?? "10");
    this.estimatedFundingBps = options.estimatedFundingBps ?? Number(process.env.NEXUS_ESTIMATED_FUNDING_BPS ?? "0");
    this.engine = new BinanceFuturesEngineCatE({
      apiKey: options.apiKey,
      apiSecret: options.apiSecret,
      testnet: this.mode === "TESTNET",
      marketType: this.market,
      maxRetries: 5,
    });
  }

  private async loadExecutionConfig(instrumentId?: string, symbol?: string): Promise<void> {
    const mode = this.mode.toLowerCase() as "testnet" | "live";
    const executionConfig = await this.telemetry.getExecutionConfig({
      riskProfileCode: this.riskProfileCode!,
      strategyCode: this.strategyCode,
      mode,
      accountId: this.accountId || undefined,
      instrumentId,
      symbol,
    });
    if (executionConfig.mode !== mode || !executionConfig.riskProfile.enabled || !executionConfig.strategy.enabled || !executionConfig.strategy.supportedModes.includes(mode)) throw new Error("Supabase execution configuration is not enabled for this mode");
    if (!executionConfig.strategy.version.id || !["validated","approved"].includes(executionConfig.strategy.version.validationStatus)) throw new Error("Strategy version has not passed validation");
    if (this.mode === "LIVE" && !executionConfig.activeGuardPolicy) throw new Error("LIVE requires an active signed Guard policy");
    if (executionConfig.circuitBreakers.length > 0) throw new Error("An applicable circuit breaker is open");
    const limits = {
      maxRiskPerTrade: executionConfig.riskProfile.maxRiskPerTrade,
      maxDailyLoss: executionConfig.riskProfile.maxDailyLoss,
      maxDrawdown: executionConfig.riskProfile.maxDrawdown,
      maxLeverage: executionConfig.riskProfile.maxLeverage,
      maxOpenOrders: executionConfig.riskProfile.maxOpenOrders,
      maxPositionNotional: executionConfig.riskProfile.maxPositionNotional,
      maxSlippageBps: executionConfig.riskProfile.maxSlippageBps,
      maxFeeBps: executionConfig.riskProfile.maxFeeBps,
      maxFundingBps: executionConfig.riskProfile.maxFundingBps,
      maxConcentration: executionConfig.riskProfile.maxConcentration,
      minRewardRisk: executionConfig.riskProfile.minRewardRisk,
    };
    this.riskEngine = new RiskEngine(parseRiskLimits(JSON.stringify(limits)));
    this.executionConfig = executionConfig;
  }

  async initialize(): Promise<void> {
    if (this.initialized) return;
    try {
      await this.engine.initialize();
      this.hedgeMode = (await this.engine.getPositionMode()).dualSidePosition;
      this.engine.on("orderUpdate", this.orderUpdateHandler);
      const account = await this.telemetry.registerVenueAccount({
        venue: "binance",
        accountLabel: this.accountLabel,
        environment: this.mode === "TESTNET" ? "testnet" : "production",
        accountType: "futures",
        capabilities: { market: this.market, userDataStream: true, executionMode: this.mode.toLowerCase() },
      });
      this.accountId = account.id;
      await this.loadExecutionConfig();
      await this.syncFundingIncome();
      await this.refreshSnapshot();
      this.initialized = true;
    } catch (error) {
      this.engine.off("orderUpdate", this.orderUpdateHandler);
      this.engine.terminate();
      this.initialized = false;
      throw error;
    }
  }

  private async exchangeSymbol(symbol: string): Promise<BinanceExchangeSymbol> {
    const response = await this.engine.getExchangeInfo(symbol);
    const item = response.symbols.find((entry) => entry.symbol === symbol);
    if (!item || item.status !== "TRADING") throw new Error("Exchange instrument is not in TRADING status: " + symbol);
    return item;
  }

  private async ensureInstrument(symbol: string): Promise<string> {
    const existing = this.instrumentIds.get(symbol);
    if (existing) return existing;
    const item = await this.exchangeSymbol(symbol);
    const priceFilter = item.filters.find((filter) => filter.filterType === "PRICE_FILTER");
    const lotFilter = item.filters.find((filter) => filter.filterType === "LOT_SIZE");
    const notionalFilter = item.filters.find((filter) => filter.filterType === "MIN_NOTIONAL" || filter.filterType === "NOTIONAL");
    if (!priceFilter?.tickSize || !lotFilter?.stepSize || !lotFilter?.minQty) throw new Error("Exchange instrument filters are incomplete: " + symbol);
    const marketType = item.contractType === "PERPETUAL" ? "perpetual" : "future";
    const registered = await this.telemetry.registerInstrument({
      venue: "binance",
      marketType,
      symbol: item.symbol,
      baseAsset: item.baseAsset,
      quoteAsset: item.quoteAsset,
      settlementAsset: item.marginAsset ?? item.quoteAsset,
      priceTick: priceFilter.tickSize,
      quantityStep: lotFilter.stepSize,
      minQuantity: lotFilter.minQty,
      minNotional: notionalFilter?.notional ?? notionalFilter?.minNotional ?? "0",
      contractMultiplier: item.contractSize ?? "1",
      active: true,
      metadata: { contractType: item.contractType ?? null, status: item.status, market: this.market },
    });
    this.instrumentIds.set(symbol, registered.id);
    this.contractSizes.set(symbol, Number(item.contractSize ?? 1));
    this.instrumentSettlementAssets.set(symbol, item.marginAsset ?? item.quoteAsset);
    return registered.id;
  }

  async markPrice(symbol: string): Promise<number> {
    if (!this.initialized) throw new Error("Binance execution adapter is not initialized");
    const premium = await this.engine.getPremiumIndex(symbol);
    const price = Number(premium.markPrice);
    if (!Number.isFinite(price) || price <= 0) throw new Error("Binance mark price is invalid for " + symbol);
    return price;
  }

  snapshot(): ExecutionSnapshot {
    if (!this.initialized) throw new Error("Binance execution adapter is not initialized");
    return { mode: this.mode, market: this.market, balance: this.balance, positions: [...this.positions], fills: [...this.fills] };
  }

  async terminate(): Promise<void> { this.engine.off("orderUpdate", this.orderUpdateHandler); this.engine.terminate(); this.initialized = false; }
}
