# python_engine/funding/funding_scanner.py
"""Funding rate scanner: collects funding rates from provided market data and suggests capture opportunities.
"""
from typing import Dict, Any, List

class FundingScanner:
    def __init__(self, min_profit_per_day: float = 0.0005):
        self.min_profit_per_day = min_profit_per_day

    def evaluate(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """markets: list of {symbol, fundingRate, notional, cost_estimate}
        returns list of capture opportunities
        """
        res = []
        for m in markets:
            fr = float(m.get('fundingRate', 0.0))
            notional = float(m.get('notional', 0.0))
            cost = float(m.get('cost_estimate', 0.0))
            expected = fr * notional - cost
            if expected / max(1.0, notional) >= self.min_profit_per_day:
                res.append({'symbol': m.get('symbol'), 'expected': expected, 'fundingRate': fr})
        return res
