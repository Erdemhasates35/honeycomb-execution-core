export type NexusTelemetryKind =
  | "venue_account"
  | "instrument"
  | "order_intent"
  | "risk_decision"
  | "order_event"
  | "fill"
  | "position"
  | "balance"
  | "pnl"
  | "heartbeat"
  | "reconciliation"
  | "discrepancy";

export interface NexusTelemetryConfig {
  endpoint: string;
  token: string;
  fetcher?: typeof fetch;
  timeoutMs?: number;
}

export interface NexusTelemetryResult {
  id: string;
  kind: NexusTelemetryKind;
}

export class NexusTelemetryError extends Error {
  readonly status: number;
  readonly kind: NexusTelemetryKind;
  constructor(kind: NexusTelemetryKind, status: number, message: string) {
    super(message);
    this.name = "NexusTelemetryError";
    this.kind = kind;
    this.status = status;
  }
}

export class NexusTelemetryClient {
  private readonly endpoint: string;
  private readonly token: string;
  private readonly fetcher: typeof fetch;
  private readonly timeoutMs: number;

  constructor(config: NexusTelemetryConfig) {
    const endpoint = config.endpoint.trim();
    const token = config.token.trim();
    if (!/^https:\/\//i.test(endpoint)) throw new Error("NEXUS_TELEMETRY_URL must be an HTTPS URL");
    if (!token || token.length > 512) throw new Error("NEXUS_TELEMETRY_TOKEN is missing or invalid");
    this.endpoint = endpoint.replace(/\/+$/, "");
    this.token = token;
    this.fetcher = config.fetcher ?? fetch;
    this.timeoutMs = config.timeoutMs ?? 5000;
    if (!Number.isInteger(this.timeoutMs) || this.timeoutMs < 500 || this.timeoutMs > 30000) throw new Error("Invalid telemetry timeout");
  }

  static fromEnv(env: NodeJS.ProcessEnv = process.env, fetcher: typeof fetch = fetch): NexusTelemetryClient {
    return new NexusTelemetryClient({
      endpoint: env.NEXUS_TELEMETRY_URL ?? "",
      token: env.NEXUS_TELEMETRY_TOKEN ?? "",
      fetcher,
      timeoutMs: Number(env.NEXUS_TELEMETRY_TIMEOUT_MS ?? "5000"),
    });
  }

  async record(kind: NexusTelemetryKind, record: Record<string, unknown>): Promise<NexusTelemetryResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetcher(this.endpoint, {
        method: "POST",
        headers: {
          authorization: `Bearer ${this.token}`,
          "content-type": "application/json",
          "cache-control": "no-store",
        },
        body: JSON.stringify({ kind, record }),
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => null) as { ok?: boolean; id?: string; error?: string } | null;
      if (!response.ok || payload?.ok !== true || typeof payload.id !== "string" || payload.id.length === 0) {
        throw new NexusTelemetryError(kind, response.status, payload?.error ?? "Nexus telemetry write was not acknowledged");
      }
      return { id: payload.id, kind };
    } catch (error) {
      if (error instanceof NexusTelemetryError) throw error;
      if (controller.signal.aborted) throw new NexusTelemetryError(kind, 408, "Nexus telemetry request timed out");
      throw new NexusTelemetryError(kind, 0, error instanceof Error ? error.message : "Nexus telemetry transport failed");
    } finally {
      clearTimeout(timeout);
    }
  }

  registerVenueAccount(input: {
    venue: string;
    accountLabel: string;
    environment: "production" | "testnet";
    accountType?: string;
    capabilities?: Record<string, unknown>;
  }): Promise<NexusTelemetryResult> {
    return this.record("venue_account", {
      venue: input.venue,
      account_label: input.accountLabel,
      environment: input.environment,
      account_type: input.accountType ?? "unified",
      capabilities: input.capabilities ?? {},
    });
  }

  registerInstrument(input: {
    venue: string;
    marketType: "spot" | "perpetual" | "future" | "option" | "swap";
    symbol: string;
    baseAsset: string;
    quoteAsset: string;
    settlementAsset?: string;
    priceTick: string;
    quantityStep: string;
    minQuantity: string;
    minNotional?: string;
    contractMultiplier?: string;
    makerFeeBps?: string;
    takerFeeBps?: string;
    active?: boolean;
    metadata?: Record<string, unknown>;
  }): Promise<NexusTelemetryResult> {
    return this.record("instrument", {
      venue: input.venue,
      market_type: input.marketType,
      symbol: input.symbol,
      base_asset: input.baseAsset,
      quote_asset: input.quoteAsset,
      settlement_asset: input.settlementAsset ?? null,
      price_tick: input.priceTick,
      quantity_step: input.quantityStep,
      min_quantity: input.minQuantity,
      min_notional: input.minNotional ?? "0",
      contract_multiplier: input.contractMultiplier ?? "1",
      maker_fee_bps: input.makerFeeBps ?? null,
      taker_fee_bps: input.takerFeeBps ?? null,
      active: input.active ?? true,
      metadata: input.metadata ?? {},
    });
  }

  createOrderIntent(input: {
    strategyCode: string;
    accountId: string;
    instrumentId: string;
    clientOrderId: string;
    idempotencyKey: string;
    side: "buy" | "sell";
    positionSide?: "LONG" | "SHORT";
    quantity: string;
    requestedMode: "testnet" | "live";
    riskProfileCode?: string;
    reduceOnly?: boolean;
    postOnly?: boolean;
    stopPrice?: string;
    metadata?: Record<string, unknown>;
  }): Promise<NexusTelemetryResult> {
    return this.record("order_intent", {
      strategy_code: input.strategyCode,
      account_id: input.accountId,
      instrument_id: input.instrumentId,
      client_order_id: input.clientOrderId,
      idempotency_key: input.idempotencyKey,
      side: input.side,
      position_side: input.positionSide?.toLowerCase() ?? null,
      order_type: "market",
      quantity: input.quantity,
      requested_mode: input.requestedMode,
      risk_profile_code: input.riskProfileCode ?? null,
      reduce_only: input.reduceOnly ?? false,
      post_only: input.postOnly ?? false,
      stop_price: input.stopPrice ?? null,
      metadata: input.metadata ?? {},
    });
  }

  recordRiskDecision(input: {
    intentId: string;
    profileCode?: string;
    decision: "allow" | "deny" | "reduce" | "defer";
    reasonCode: string;
    explanation?: string;
    metrics?: Record<string, unknown>;
  }): Promise<NexusTelemetryResult> {
    return this.record("risk_decision", {
      intent_id: input.intentId,
      profile_code: input.profileCode ?? null,
      decision: input.decision,
      reason_code: input.reasonCode,
      explanation: input.explanation ?? "",
      metrics: input.metrics ?? {},
    });
  }

  recordOrderEvent(input: {
    intentId: string;
    venueOrderId?: string;
    eventUid: string;
    eventType: string;
    exchangeStatus?: string;
    cumulativeQuantity?: string;
    lastFillQuantity?: string;
    averageFillPrice?: string;
    exchangeTimestamp?: string;
    payload?: Record<string, unknown>;
  }): Promise<NexusTelemetryResult> {
    return this.record("order_event", {
      intent_id: input.intentId,
      venue_order_id: input.venueOrderId ?? null,
      event_uid: input.eventUid,
      event_type: input.eventType,
      exchange_status: input.exchangeStatus ?? null,
      cumulative_quantity: input.cumulativeQuantity ?? null,
      last_fill_quantity: input.lastFillQuantity ?? null,
      average_fill_price: input.averageFillPrice ?? null,
      exchange_timestamp: input.exchangeTimestamp ?? null,
      payload: input.payload ?? {},
    });
  }

  recordPnl(input: {
    accountId: string;
    intentId?: string;
    fillId?: string;
    entryType: "realized_pnl" | "fee" | "funding" | "rebate" | "borrow_interest" | "gas" | "slippage" | "transfer" | "adjustment";
    asset: string;
    amount: string;
    sourceReference: string;
    occurredAt: string;
    usdConversionRate?: string;
    amountUsd?: string;
    metadata?: Record<string, unknown>;
  }): Promise<NexusTelemetryResult> {
    return this.record("pnl", {
      account_id: input.accountId,
      intent_id: input.intentId ?? null,
      fill_id: input.fillId ?? null,
      entry_type: input.entryType,
      asset: input.asset,
      amount: input.amount,
      usd_conversion_rate: input.usdConversionRate ?? null,
      amount_usd: input.amountUsd ?? null,
      source_reference: input.sourceReference,
      occurred_at: input.occurredAt,
      metadata: input.metadata ?? {},
    });
  }

  authorizeLive(input: {
    intentId: string;
    executorId: string;
    approvalDigest: string;
  }): Promise<NexusTelemetryResult> {
    return this.record("authorize_live", {
      intent_id: input.intentId,
      executor_id: input.executorId,
      approval_digest: input.approvalDigest,
    });
  }

  recordSubmissionResult(input: {
    authorizationId: string;
    executorId: string;
    outcome: "submitted" | "unknown" | "failed";
    venueOrderId?: string;
    errorCode?: string;
  }): Promise<NexusTelemetryResult> {
    return this.record("submission_result", {
      authorization_id: input.authorizationId,
      executor_id: input.executorId,
      outcome: input.outcome,
      venue_order_id: input.venueOrderId ?? null,
      error_code: input.errorCode ?? null,
    });
  }

  recordFill(input: {
    intentId: string;
    orderEventId?: string;
    accountId: string;
    instrumentId: string;
    venueTradeId: string;
    side: "buy" | "sell";
    quantity: string;
    price: string;
    feeAmount: string;
    feeAsset: string;
    liquidityRole?: "maker" | "taker" | "unknown";
    executedAt: string;
    source: string;
    rawDigest?: string;
  }): Promise<NexusTelemetryResult> {
    return this.record("fill", {
      intent_id: input.intentId,
      order_event_id: input.orderEventId ?? null,
      account_id: input.accountId,
      instrument_id: input.instrumentId,
      venue_trade_id: input.venueTradeId,
      side: input.side,
      quantity: input.quantity,
      price: input.price,
      fee_amount: input.feeAmount,
      fee_asset: input.feeAsset,
      liquidity_role: input.liquidityRole ?? "unknown",
      executed_at: input.executedAt,
      source: input.source,
      raw_digest: input.rawDigest ?? null,
    });
  }
}
