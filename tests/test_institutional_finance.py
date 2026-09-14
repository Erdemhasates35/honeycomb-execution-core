import math

from institutional_finance import (
    directional_expected_move_bps,
    funding_cost_fraction,
    net_edge_bps,
    pnl_percent,
    position_size_from_risk,
    dynamic_exit_surface,
)


def test_directional_expected_move_preserves_side():
    assert directional_expected_move_bps(0.65, 40.0, 2.0, "LONG") > 0
    assert directional_expected_move_bps(0.65, 40.0, 2.0, "SHORT") > 0
    assert directional_expected_move_bps(-0.65, 40.0, 2.0, "LONG") < 0


def test_funding_is_zero_before_next_settlement():
    assert funding_cost_fraction(0.0001, "LONG", 3600, 7200) == 0.0


def test_funding_charges_only_crossed_settlements():
    assert math.isclose(funding_cost_fraction(0.0001, "LONG", 7201, 7200), 0.0001)
    assert math.isclose(funding_cost_fraction(0.0001, "SHORT", 7201, 7200), -0.0001)


def test_net_edge_includes_round_trip_costs_and_direction():
    assert net_edge_bps(100.0, maker_fee_rate=0.0002, taker_fee_rate=0.0005, spread_bps=2.0, slippage_bps=1.0, funding_bps=3.0, style="TAKER") == 84.0
    assert net_edge_bps(-10.0, maker_fee_rate=0.0002, taker_fee_rate=0.0005, spread_bps=2.0, slippage_bps=1.0, funding_bps=0.0, style="TAKER") < 0


def test_pnl_percent_is_margin_return_not_leveraged_price_return():
    assert math.isclose(pnl_percent("LONG", 100.0, 101.0, 10.0, 100.0, 0.001), 9.0)


def test_position_size_is_capped_by_risk_and_notional():
    result = position_size_from_risk(equity=1000.0, risk_fraction=0.05, stop_distance_pct=1.0, leverage=50, max_notional=10000, price=100.0)
    assert result["margin"] == 50.0
    assert result["notional"] == 2500.0
    assert result["quantity"] == 25.0


def test_dynamic_exit_surface_respects_direction_and_regime():
    long_exit = dynamic_exit_surface("LONG", 100.0, 2.0, 80.0, 1.5, 0.8)
    short_exit = dynamic_exit_surface("SHORT", 100.0, 2.0, 80.0, 1.5, 0.8)
    assert long_exit["tp"] > 100.0 and long_exit["sl"] < 100.0
    assert short_exit["tp"] < 100.0 and short_exit["sl"] > 100.0
