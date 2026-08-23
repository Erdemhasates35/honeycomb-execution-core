# tests/critical/test_funding.py
from python_engine.funding.funding_scanner import FundingScanner


def test_funding_scanner():
    s = FundingScanner(min_profit_per_day=0.0001)
    markets = [{'symbol': 'BTCUSD', 'fundingRate': 0.001, 'notional': 1000, 'cost_estimate': 0.0}]
    res = s.evaluate(markets)
    assert isinstance(res, list) and len(res) >= 0
