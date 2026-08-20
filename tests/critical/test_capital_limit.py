# tests/critical/test_capital_limit.py
from python_engine.engine import RiskEngine, OrderEngine, MockGateway


def test_capital_limit_allows_within_percent():
    risk = RiskEngine(live_max_capital_percent=10.0, max_leverage=50)
    max_notional = risk.calculate_max_notional(1000.0)
    assert max_notional == 100.0

    gw = MockGateway(account_equity=1000.0)
    oe = OrderEngine(gw, risk)
    order = oe.prepare_order(symbol="BTCUSDT", side="LONG", notional=100.0, requested_leverage=10, account_equity=1000.0)
    assert order["notional"] == 100.0


def test_capital_limit_blocks_over_percent():
    risk = RiskEngine(live_max_capital_percent=5.0, max_leverage=50)
    gw = MockGateway(account_equity=2000.0)
    oe = OrderEngine(gw, risk)
    try:
        oe.prepare_order(symbol="BTCUSDT", side="LONG", notional=201.0, requested_leverage=10, account_equity=2000.0)
        assert False, "should have raised"
    except ValueError as e:
        assert str(e) == "capital_limit_exceeded"
