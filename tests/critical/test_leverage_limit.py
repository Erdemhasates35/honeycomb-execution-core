# tests/critical/test_leverage_limit.py
from python_engine.engine import RiskEngine, OrderEngine, MockGateway


def test_leverage_enforcement():
    risk = RiskEngine(live_max_capital_percent=10.0, max_leverage=50)
    gw = MockGateway(account_equity=1000.0)
    oe = OrderEngine(gw, risk)
    order = oe.prepare_order(symbol="BTCUSDT", side="LONG", notional=50.0, requested_leverage=100, account_equity=1000.0)
    assert order["leverage"] == 50

    order2 = oe.prepare_order(symbol="BTCUSDT", side="LONG", notional=50.0, requested_leverage=5, account_equity=1000.0)
    assert order2["leverage"] == 5
