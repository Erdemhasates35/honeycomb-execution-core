# python_engine/stat_arb/cointegration.py
"""Statistical arbitrage (cointegration) skeleton using simple OLS residual z-score approach.
"""
import numpy as np
from typing import Tuple, List

class PairStatArb:
    def half_life(self, spread: List[float]) -> float:
        # naive half-life estimate using AR(1) on spread
        if len(spread) < 3:
            return float('inf')
        x = np.array(spread[:-1])
        y = np.array(spread[1:])
        beta = np.polyfit(x, y, 1)[0]
        halflife = -np.log(2) / np.log(beta) if beta>0 else float('inf')
        return halflife

    def zscore(self, spread: List[float]) -> float:
        if not spread:
            return 0.0
        s = np.array(spread)
        return (s[-1] - s.mean()) / (s.std() if s.std() > 0 else 1.0)
