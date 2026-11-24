import { randomUUID } from "node:crypto";
import { BinanceFuturesEngineCatE, type BinanceExchangeSymbol, type BinanceOrderStatus, type BinanceUserTrade } from "../BinanceFuturesEngineCatE.js";
import { reconcileBinanceUserTrades } from "./binance_fill.js";
import { NexusTelemetryClient } from "./nexus_telemetry_client.js";
import { RiskEngine, parseRiskLimits, type RiskContext } from "./risk_engine.js";
import type { ExecutionAdapter, ExecutionMode, ExecutionSnapshot, Fill, FuturesMarket, OrderIntent, Position } from "./types.js";

interface BalanceRow {
  asset: string;
  balance?: string;
  walletBalance?: string;
  availableBalance?: string;
  withdrawAvailable?: string;
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
  private readonly riskEngine: RiskEngine;
  private readonly riskContextOverrides: RiskContextOverrides;
  private readonly estimatedSlippageBps: number;
  private readonly estimatedFeeBps: number;
  private readonly estimatedFundingBps: number;
  private readonly fills: Fill[] = [];
  private readonly instrumentIds = new Map<string,string>();
  private readonly contractSizes = new Map<string,number>();
  private accountId = "";
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
    if (this.mode === "LIVE" && (!this.riskProfileCode || !this.executorId)) throw new Error("LIVE requires NEXUS_RISK_PROFILE_CODE and NEXUS_EXECUTOR_ID");
    const riskLimitsJson = options.riskLimitsJson ?? process.env.NEXUS_RISK_PROFILE_JSON ?? "";
    if (!riskLimitsJson) throw new Error("NEXUS_RISK_PROFILE_JSON is required for TESTNET and LIVE");
    this.riskEngine = new RiskEngine(parseRiskLimits(riskLimitsJson));
    const riskContextJson = options.riskContextJson ?? process.env.NEXUS_RISK_CONTEXT_JSON;
    if (this.mode === "LIVE" && !riskContextJson) throw new Error("LIVE requires NEXUS_RISK_CONTEXT_JSON with current high-water mark and daily realized PnL");
    try {
      this.riskContextOverrides = riskContextJson ? JSON.parse(riskContextJson) as RiskContextOverrides : {};
    } catch {
      throw new Error("NEXUS_RISK_CONTEXT_JSON is invalid JSON");
    }
    if (this.mode === "LIVE") {
      const requiredContext = ["peakEquity","dailyRealizedPnl","openOrders","portfolioNotional","estimatedSlippageBps","estimatedFeeBps","estimatedFundingBps"] as const;
      for (const key of requiredContext) {
        if (typeof this.riskContextOverrides[key] !== "number" || !Number.isFinite(this.riskContextOverrides[key])) throw new Error("LIVE risk context is missing a current numeric " + key);
      }
    }
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

  async initialize(): Promise<void> {
    await this.engine.initialize();
    const account = await this.telemetry.registerVenueAccount({
      venue: "binance",
      accountLabel: this.accountLabel,
      environment: this.mode === "TESTNET" ? "testnet" : "production",
      accountType: "futures",
      capabilities: { market: this.market, userDataStream: true, executionMode: this.mode.toLowerCase() },
    });
    this.accountId = account.id;
    await this.refreshSnapshot();
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
    return registered.id;
  }

  async markPrice(symbol: string): Promise<number> {
    const prefix = this.market === "COIN_M" ? "dapi" : "fapi";
    const base = this.mode === "TESTNET"
      ? "https://testnet.binancefuture.com"
      : (this.market === "COIN_M" ? "https://dapi.binance.com" : "https://fapi.binance.com");
    const response = await fetch(`${base}/${prefix}/v1/ticker/price?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Binance ticker failed: HTTP ${response.status}`);
    const data = await response.json() as { price?: string };
    const price = Number(data.price);
    if (!Number.isFinite(price) || price <= 0) throw new Error("Invalid exchange mark price: " + symbol);
    return price;
  }

  private riskContext(symbol: string, price: number): RiskContext {
    const positionsNotional = this.positions.reduce((sum, position) => {
      const contractSize = this.contractSizes.get(position.symbol) ?? 1;
      return sum + (this.market === 'COIN_M' ? Math.abs(position.quantity * contractSize) : Math.abs(position.quantity * position.entryPrice * contractSize));
    }, 0);
    const contractSize = this.contractSizes.get(symbol) ?? 1;
    const equity = this.market === 'COIN_M' ? this.balance * price : this.balance;
    const peakEquity = this.riskContextOverrides.peakEquity ?? equity;
    const dailyRealizedPnl = this.riskContextOverrides.dailyRealizedPnl ?? 0;
    const openOrders = this.riskContextOverrides.openOrders ?? this.positions.length;
    const portfolioNotional = this.riskContextOverrides.portfolioNotional ?? positionsNotional;
    const context: RiskContext = {
      equity,
      peakEquity,
      availableBalance: equity,
      dailyRealizedPnl,
      openOrders,
      portfolioNotional,
      estimatedSlippageBps: this.riskContextOverrides.estimatedSlippageBps ?? this.estimatedSlippageBps,
      estimatedFeeBps: this.riskContextOverrides.estimatedFeeBps ?? this.estimatedFeeBps,
      estimatedFundingBps: this.riskContextOverrides.estimatedFundingBps ?? this.estimatedFundingBps,
      contractMultiplier: this.market === 'COIN_M' ? contractSize / price : contractSize,
    };
    return context;
  }

  private async refreshSnapshot(): Promise<void> {
    const [rawBalances, rawPositions] = await Promise.all([
      this.engine.getAccountBalance(),
      this.engine.getPositionRisk(),
    ]);
    const balances = rawBalances as BalanceRow[];
    const balanceRow = balances.find((row) => row.asset === this.settlementAsset);
    if (!balanceRow) throw new Error("Settlement asset balance is unavailable: " + this.settlementAsset);
    const available = Number(balanceRow.availableBalance ?? balanceRow.withdrawAvailable ?? balanceRow.balance ?? balanceRow.walletBalance);
    if (!Number.isFinite(available) || available < 0) throw new Error("Exchange returned an invalid available balance");
    this.balance = available;
    this.positions = rawPositions
      .filter((position) => Number(position.positionAmt) !== 0)
      .map((position) => ({
        symbol: position.symbol,
        side: Number(position.positionAmt) > 0 ? "LONG" : "SHORT",
        quantity: Math.abs(Number(position.positionAmt)),
        entryPrice: Number(position.entryPrice),
        leverage: Number(position.leverage),
        realizedPnl: 0,
        unrealizedPnl: Number(position.unRealizedProfit),
        feePaid: 0,
        settlementAsset: this.settlementAsset,
      }));
    const observedAt = new Date().toISOString();
    const walletBalance = Number(balanceRow.walletBalance ?? balanceRow.balance ?? available);
    const lockedBalance = Math.max(0, walletBalance - available);
    const unrealizedPnl = rawPositions.reduce((sum, position) => sum + Number(position.unRealizedProfit ?? 0), 0);
    await this.telemetry.record("balance", {
      account_id: this.accountId,
      asset: this.settlementAsset,
      wallet_balance: String(walletBalance),
      available_balance: String(available),
      locked_balance: String(lockedBalance),
      unrealized_pnl: String(unrealizedPnl),
      observed_at: observedAt,
      source: "binance_account_balance",
      metadata: { mode: this.mode, market: this.market },
    });
    for (const position of rawPositions.filter((item) => Number(item.positionAmt) !== 0)) {
      const instrumentId = await this.ensureInstrument(position.symbol);
      const amount = Math.abs(Number(position.positionAmt));
      await this.telemetry.record("position", {
        account_id: this.accountId,
        instrument_id: instrumentId,
        position_side: position.positionSide === "BOTH" ? (Number(position.positionAmt) > 0 ? "long" : "short") : String(position.positionSide).toLowerCase(),
        quantity: String(amount),
        entry_price: position.entryPrice,
        mark_price: position.markPrice,
        liquidation_price: position.liquidationPrice || null,
        leverage: position.leverage,
        initial_margin: position.isolatedMargin || null,
        maintenance_margin: null,
        realized_pnl: "0",
        unrealized_pnl: position.unRealizedProfit,
        observed_at: observedAt,
        source: "binance_position_risk",
        metadata: { marginType: position.marginType, positionSide: position.positionSide, mode: this.mode },
      });
    }
  }

  async place(intent: OrderIntent): Promise<Fill> {
    if (!Number.isFinite(intent.quantity) || intent.quantity <= 0) throw new Error("Order quantity must be finite and positive");
    if (!this.accountId) throw new Error("Execution adapter is not initialized");
    const instrumentId = await this.ensureInstrument(intent.symbol);
    const price = intent.referencePrice ?? await this.markPrice(intent.symbol);
    const clientOrderId = intent.clientOrderId ?? `hc-${randomUUID().replace(/-/g,"").slice(0,32)}`;
    const strategyCode = intent.strategyCode ?? this.strategyCode;
    const riskProfileCode = intent.riskProfileCode ?? this.riskProfileCode;
    const requestedMode = this.mode === "TESTNET" ? "testnet" : "live";
    const intentResult = await this.telemetry.createOrderIntent({
      strategyCode,
      accountId: this.accountId,
      instrumentId,
      clientOrderId,
      idempotencyKey: intent.idempotencyKey ?? clientOrderId,
      side: intent.side === "LONG" ? "buy" : "sell",
      quantity: String(intent.quantity),
      requestedMode,
      riskProfileCode,
      reduceOnly: intent.reduceOnly,
      stopPrice: intent.stopLossPrice === undefined ? undefined : String(intent.stopLossPrice),
      metadata: { market: this.market, leverage: intent.leverage ?? 1, takeProfitPrice: intent.takeProfitPrice ?? null, reduceOnly: intent.reduceOnly ?? false },
    });
    const decision = this.riskEngine.evaluate(intent, price, this.riskContext(intent.symbol, price));
    await this.telemetry.recordRiskDecision({
      intentId: intentResult.id,
      profileCode: riskProfileCode,
      decision: decision.decision,
      reasonCode: decision.reasonCode,
      explanation: decision.decision === "allow" ? "All configured risk limits passed" : "Order rejected by the local risk engine",
      metrics: decision.metrics,
    });
    if (decision.decision !== "allow") throw new Error("Risk engine rejected order: " + decision.reasonCode);

    let authorizationId: string | undefined;
    if (this.mode === "LIVE") {
      if (!intent.guardApprovalDigest) throw new Error("LIVE requires a per-intent signed Guard approval digest");
      const authorization = await this.telemetry.authorizeLive({
        intentId: intentResult.id,
        executorId: this.executorId!,
        approvalDigest: intent.guardApprovalDigest,
      });
      authorizationId = authorization.id;
    }

    let order: BinanceOrderStatus;
    try {
      order = await this.engine.executeOrder({
        symbol: intent.symbol,
        side: intent.side === "LONG" ? "BUY" : "SELL",
        type: "MARKET",
        quantity: intent.quantity,
        reduceOnly: intent.reduceOnly,
        clientOrderId,
      }) as BinanceOrderStatus;
    } catch (error) {
      if (authorizationId) {
        await this.telemetry.recordSubmissionResult({ authorizationId, executorId: this.executorId!, outcome: "unknown", errorCode: "exchange_submission_ambiguous" });
      }
      await this.telemetry.recordOrderEvent({
        intentId: intentResult.id,
        eventUid: `binance:${this.market}:${clientOrderId}:unknown`,
        eventType: "submission_unknown",
        exchangeStatus: "UNKNOWN",
        payload: { error: error instanceof Error ? error.message : "exchange submission failed" },
      });
      throw error;
    }

    const orderId = Number(order.orderId);
    if (!Number.isSafeInteger(orderId) || orderId <= 0) {
      if (authorizationId) await this.telemetry.recordSubmissionResult({ authorizationId, executorId: this.executorId!, outcome: "unknown", errorCode: "missing_exchange_order_id" });
      throw new Error("Binance returned an invalid order ID");
    }

    if (authorizationId) {
      await this.telemetry.recordSubmissionResult({ authorizationId, executorId: this.executorId!, outcome: "submitted", venueOrderId: String(order.orderId) });
    }

    let finalOrder: BinanceOrderStatus;
    try {
      if (order.status === "NEW" || order.status === "PARTIALLY_FILLED") {
        try { await this.engine.cancelOrder(intent.symbol, orderId); } catch {}
      }
      finalOrder = await this.engine.getOrder(intent.symbol, orderId);
      if (finalOrder.status === "NEW" || finalOrder.status === "PARTIALLY_FILLED") throw new Error("Open order remainder was not canceled");
    } catch (error) {
      await this.telemetry.recordOrderEvent({
        intentId: intentResult.id,
        venueOrderId: String(order.orderId),
        eventUid: `binance:${this.market}:${orderId}:unreconciled:${Date.now()}`,
        eventType: "order_reconciliation_failed",
        exchangeStatus: "UNKNOWN",
        payload: { error: error instanceof Error ? error.message : "order reconciliation failed" },
      });
      throw error;
    }

    let trades: BinanceUserTrade[];
    try {
      trades = await this.engine.getUserTrades(intent.symbol, orderId);
    } catch (error) {
      await this.telemetry.recordOrderEvent({
        intentId: intentResult.id,
        venueOrderId: String(orderId),
        eventUid: `binance:${this.market}:${orderId}:user-trades-unavailable:${Date.now()}`,
        eventType: "fill_ledger_unavailable",
        exchangeStatus: "UNKNOWN",
        cumulativeQuantity: finalOrder.executedQty,
        payload: { error: error instanceof Error ? error.message : "user trades unavailable" },
      });
      throw error;
    }
    const eventUid = `binance:${this.market}:${orderId}:${finalOrder.status}:${finalOrder.executedQty}:${finalOrder.updateTime ?? Date.now()}`;
    if (Number(finalOrder.executedQty) === 0) {
      await this.telemetry.recordOrderEvent({
        intentId: intentResult.id,
        venueOrderId: String(orderId),
        eventUid,
        eventType: "order_terminal_without_fill",
        exchangeStatus: finalOrder.status,
        cumulativeQuantity: "0",
        exchangeTimestamp: new Date(finalOrder.updateTime ?? Date.now()).toISOString(),
        payload: { tradeCount: trades.length, market: this.market },
      });
      throw new Error("Binance order reached a terminal state without an executed fill");
    }
    let reconciled;
    try {
      reconciled = reconcileBinanceUserTrades(finalOrder, trades, { ...intent, clientOrderId }, this.market, this.mode);
    } catch (error) {
      await this.telemetry.recordOrderEvent({
        intentId: intentResult.id,
        venueOrderId: String(orderId),
        eventUid: eventUid + ":reconciliation-failed",
        eventType: "fill_reconciliation_failed",
        exchangeStatus: "UNKNOWN",
        cumulativeQuantity: finalOrder.executedQty,
        exchangeTimestamp: new Date(finalOrder.updateTime ?? Date.now()).toISOString(),
        payload: { error: error instanceof Error ? error.message : "fill reconciliation failed", tradeCount: trades.length },
      });
      throw error;
    }
    const orderEvent = await this.telemetry.recordOrderEvent({
      intentId: intentResult.id,
      venueOrderId: String(orderId),
      eventUid,
      eventType: "order_reconciled",
      exchangeStatus: finalOrder.status,
      cumulativeQuantity: finalOrder.executedQty,
      averageFillPrice: reconciled.fill.price.toString(),
      exchangeTimestamp: new Date(finalOrder.updateTime ?? Date.now()).toISOString(),
      payload: { tradeCount: trades.length, market: this.market },
    });

    for (const trade of reconciled.trades) {
      const fillRecord = await this.telemetry.recordFill({
        intentId: intentResult.id,
        orderEventId: orderEvent.id,
        accountId: this.accountId,
        instrumentId,
        venueTradeId: String(trade.id),
        side: intent.side === "LONG" ? "buy" : "sell",
        quantity: trade.qty,
        price: trade.price,
        feeAmount: trade.commission,
        feeAsset: trade.commissionAsset,
        liquidityRole: trade.maker ? "maker" : "taker",
        executedAt: new Date(trade.time).toISOString(),
        source: "binance_userTrades",
      });
      if (trade.realizedPnl && Number(trade.realizedPnl) !== 0) {
        await this.telemetry.recordPnl({
          accountId: this.accountId,
          intentId: intentResult.id,
          fillId: fillRecord.id,
          entryType: "realized_pnl",
          asset: this.settlementAsset,
          amount: trade.realizedPnl,
          sourceReference: `binance:${this.market}:${intent.symbol}:${trade.id}:realized_pnl`,
          occurredAt: new Date(trade.time).toISOString(),
          metadata: { orderId, market: this.market },
        });
      }
      if (Number(trade.commission) > 0) {
        await this.telemetry.recordPnl({
          accountId: this.accountId,
          intentId: intentResult.id,
          fillId: fillRecord.id,
          entryType: "fee",
          asset: trade.commissionAsset,
          amount: trade.commission.startsWith("-") ? trade.commission : "-" + trade.commission,
          sourceReference: `binance:${this.market}:${intent.symbol}:${trade.id}:fee`,
          occurredAt: new Date(trade.time).toISOString(),
          metadata: { orderId, liquidityRole: trade.maker ? "maker" : "taker" },
        });
      }
    }

    this.fills.push(reconciled.fill);
    await this.refreshSnapshot();
    return reconciled.fill;
  }

  async close(symbol: string, referencePrice?: number, guardApprovalDigest?: string): Promise<Fill | null> {
    const positions = await this.engine.getPositionRisk(symbol);
    const active = positions.find((position) => Number(position.positionAmt) !== 0);
    if (!active) return null;
    return this.place({
      symbol,
      side: Number(active.positionAmt) > 0 ? "SHORT" : "LONG",
      quantity: Math.abs(Number(active.positionAmt)),
      referencePrice,
      reduceOnly: true,
      guardApprovalDigest,
    });
  }

  snapshot(): ExecutionSnapshot {
    return { mode: this.mode, market: this.market, balance: this.balance, positions: [...this.positions], fills: [...this.fills] };
  }

  async terminate(): Promise<void> { this.engine.terminate(); }
}
