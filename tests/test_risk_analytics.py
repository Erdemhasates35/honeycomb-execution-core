from risk_analytics import summarize_trades


def test_summary_reports_net_percent_profit_factor_drawdown_and_margin_return():
    result = summarize_trades([
        {"net": 10, "fee": 1, "funding": 0, "hold_sec": 60, "mae": -2, "mfe": 12, "margin": 100},
        {"net": -5, "fee": 1, "funding": 0.5, "hold_sec": 120, "mae": -7, "mfe": 3, "margin": 100},
    ], starting_equity=1000)
    assert result["net_pnl"] == 5
    assert result["net_pnl_pct_start"] == 0.5
    assert result["profit_factor"] == 2
    assert result["max_drawdown"] == 5
    assert result["net_pnl_pct_margin"] == 2.5
