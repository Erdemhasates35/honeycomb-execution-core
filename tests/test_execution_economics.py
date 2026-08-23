from decimal import Decimal as D

from execution_economics import (
    CostModel,
    break_even_win_rate,
    calculate_trade,
    expected_value_per_trade,
    normalize_legacy_fee_rate,
    risk_based_size,
)


def test_legacy_004_percent_is_4bps_not_4_percent():
    assert normalize_legacy_fee_rate("0.04") == D("0.0004")
    assert normalize_legacy_fee_rate("0.0004") == D("0.0004")


def test_legacy_fee_rejects_ambiguous_large_value():
    try:
        normalize_legacy_fee_rate("4")
    except ValueError:
        pass
    else:
        raise AssertionError("4 must not be silently interpreted as a fee rate")


def test_200_notional_two_taker_sides_at_5bps_costs_020():
    costs = CostModel.from_bps(2, 5)
    t = calculate_trade(200, D("0.50"), "LONG", costs, "taker", "taker")
    assert t.trading_fee == D("0.20000000")
    assert t.net_pnl == D("0.80000000")


def test_maker_maker_is_cheaper_than_taker_taker():
    costs = CostModel.from_bps(2, 5)
    mm = calculate_trade(200, D("0.50"), "LONG", costs, "maker", "maker")
    tt = calculate_trade(200, D("0.50"), "LONG", costs, "taker", "taker")
    assert mm.net_pnl > tt.net_pnl
    assert mm.trading_fee == D("0.08000000")


def test_break_even_for_tp_half_sl_nine_taker_fee_five_bps():
    # Round-trip trading fee is 0.10%; no other costs included here.
    p = break_even_win_rate(D("0.50"), D("0.90"), D("0.10"))
    assert p == D("0.714286")


def test_expected_value_zero_at_break_even():
    p = break_even_win_rate(D("0.50"), D("0.90"), D("0.10"))
    ev = expected_value_per_trade(p, D("0.50"), D("0.90"), D("0.10"), D("200"))
    assert abs(ev) < D("0.00001")


def test_risk_based_size_uses_stop_plus_cost_plus_buffer():
    result = risk_based_size(
        equity=D("20.81"),
        risk_fraction=D("0.01"),
        stop_pct=D("0.90"),
        total_cost_pct=D("0.10"),
        adverse_buffer_pct=D("0.10"),
        leverage_cap=D("20"),
        max_notional=D("200"),
    )
    assert result.risk_budget == D("0.20810000")
    assert result.notional > D("0")
    assert result.notional < D("25")
    assert result.margin == (result.notional / D("20")).quantize(D("0.00000001"))
