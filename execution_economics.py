"""Fee-aware execution economics for Honeycomb.

All fee inputs are explicit basis points (bps): 1 bps = 0.01% = 0.0001.
No trading decision should use the legacy ambiguous FEE_RATE directly.

The module is pure and deterministic: no network, no exchange I/O, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

D = Decimal
BPS = D("0.0001")
PCT = D("0.01")


@dataclass(frozen=True)
class CostModel:
    maker_bps: D
    taker_bps: D
    slippage_bps: D = D("0")
    spread_bps: D = D("0")
    funding_bps: D = D("0")
    other_bps: D = D("0")

    @classmethod
    def from_bps(cls, maker_bps, taker_bps, slippage_bps=0, spread_bps=0, funding_bps=0, other_bps=0) -> "CostModel":
        values = [maker_bps, taker_bps, slippage_bps, spread_bps, funding_bps, other_bps]
        parsed = [D(str(v)) for v in values]
        if any(v < 0 for v in parsed):
            raise ValueError("Cost rates cannot be negative")
        if parsed[0] > D("100") or parsed[1] > D("100"):
            raise ValueError("maker/taker fee exceeds 100 bps; verify units")
        return cls(*parsed)

    def round_trip_bps(self, entry_role: str = "taker", exit_role: str = "taker") -> D:
        roles = {"maker": self.maker_bps, "taker": self.taker_bps}
        try:
            fee = roles[entry_role.lower()] + roles[exit_role.lower()]
        except KeyError as exc:
            raise ValueError("role must be maker or taker") from exc
        return fee + self.slippage_bps + self.spread_bps + self.funding_bps + self.other_bps

    def round_trip_rate(self, entry_role: str = "taker", exit_role: str = "taker") -> D:
        return self.round_trip_bps(entry_role, exit_role) * BPS


@dataclass(frozen=True)
class TradeEconomics:
    notional: D
    gross_move_pct: D
    side: str
    entry_role: str
    exit_role: str
    gross_pnl: D
    trading_fee: D
    slippage_cost: D
    spread_cost: D
    funding_cost: D
    other_cost: D
    net_pnl: D
    net_return_on_notional_pct: D


@dataclass(frozen=True)
class SizeResult:
    risk_budget: D
    stop_pct: D
    total_cost_pct: D
    adverse_buffer_pct: D
    effective_risk_pct: D
    notional: D
    margin: D
    leverage: D


def _q(value: D, places: str = "0.00000001") -> D:
    return value.quantize(D(places), rounding=ROUND_HALF_UP)


def calculate_trade(notional, gross_move_pct, side, costs: CostModel, entry_role="taker", exit_role="taker") -> TradeEconomics:
    n = D(str(notional))
    move = D(str(gross_move_pct))
    if n <= 0:
        raise ValueError("notional must be > 0")
    if side.upper() not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")

    gross = n * move * PCT
    entry_fee_bps = costs.maker_bps if entry_role.lower() == "maker" else costs.taker_bps
    exit_fee_bps = costs.maker_bps if exit_role.lower() == "maker" else costs.taker_bps
    trading_fee = n * (entry_fee_bps + exit_fee_bps) * BPS
    slippage_cost = n * costs.slippage_bps * BPS
    spread_cost = n * costs.spread_bps * BPS
    funding_cost = n * costs.funding_bps * BPS
    other_cost = n * costs.other_bps * BPS
    total_cost = trading_fee + slippage_cost + spread_cost + funding_cost + other_cost
    net = gross - total_cost
    return TradeEconomics(
        notional=n,
        gross_move_pct=move,
        side=side.upper(),
        entry_role=entry_role,
        exit_role=exit_role,
        gross_pnl=_q(gross),
        trading_fee=_q(trading_fee),
        slippage_cost=_q(slippage_cost),
        spread_cost=_q(spread_cost),
        funding_cost=_q(funding_cost),
        other_cost=_q(other_cost),
        net_pnl=_q(net),
        net_return_on_notional_pct=_q(net / n * D("100"), "0.000001"),
    )


def break_even_win_rate(take_profit_pct, stop_loss_pct, round_trip_cost_pct) -> D:
    """Return p where p*(TP-C) - (1-p)*(SL+C) = 0."""
    tp = D(str(take_profit_pct))
    sl = D(str(stop_loss_pct))
    cost = D(str(round_trip_cost_pct))
    if tp <= 0 or sl <= 0 or cost < 0:
        raise ValueError("TP/SL must be > 0 and cost >= 0")
    win = tp - cost
    loss = sl + cost
    if win <= 0:
        return D("1")
    return _q(loss / (win + loss), "0.000001")


def expected_value_per_trade(win_rate, take_profit_pct, stop_loss_pct, round_trip_cost_pct, notional) -> D:
    p = D(str(win_rate))
    if p < 0 or p > 1:
        raise ValueError("win_rate must be between 0 and 1")
    n = D(str(notional))
    tp = D(str(take_profit_pct))
    sl = D(str(stop_loss_pct))
    c = D(str(round_trip_cost_pct))
    return _q(n * ((p * (tp - c) - (D("1") - p) * (sl + c)) * PCT))


def risk_based_size(equity, risk_fraction, stop_pct, total_cost_pct, adverse_buffer_pct, leverage_cap, max_notional, min_notional="5") -> SizeResult:
    e = D(str(equity))
    rf = D(str(risk_fraction))
    stop = D(str(stop_pct))
    cost = D(str(total_cost_pct))
    buffer = D(str(adverse_buffer_pct))
    lev = D(str(leverage_cap))
    max_n = D(str(max_notional))
    min_n = D(str(min_notional))
    if min(e, rf, stop, lev, max_n) <= 0:
        raise ValueError("equity, risk_fraction, stop_pct, leverage_cap and max_notional must be > 0")
    if cost < 0 or buffer < 0:
        raise ValueError("cost and adverse buffer must be >= 0")
    risk_budget = e * rf
    effective = stop + cost + buffer
    raw_notional = risk_budget / (effective * PCT)
    notional = max(D("0"), min(raw_notional, max_n))
    if notional < min_n:
        notional = D("0")
    margin = notional / lev if notional else D("0")
    return SizeResult(
        risk_budget=_q(risk_budget),
        stop_pct=_q(stop, "0.000001"),
        total_cost_pct=_q(cost, "0.000001"),
        adverse_buffer_pct=_q(buffer, "0.000001"),
        effective_risk_pct=_q(effective, "0.000001"),
        notional=_q(notional),
        margin=_q(margin),
        leverage=_q(lev, "0.01"),
    )


def normalize_legacy_fee_rate(value) -> D:
    """Convert legacy FEE_RATE to decimal only when its units are unambiguous."""
    v = D(str(value))
    if v < 0:
        raise ValueError("fee rate cannot be negative")
    if v < D("0.01"):
        return v
    if v < D("1"):
        return v / D("100")
    raise ValueError("ambiguous legacy FEE_RATE >= 1; use explicit *_FEE_BPS")
