# python_engine/fees/fee_optimizer.py
"""Fee rebate optimizer: simple expected value decision maker for maker vs taker.
"""
from typing import Dict, Any

class FeeOptimizer:
    def __init__(self, maker_rebate: float = 0.0002, taker_fee: float = 0.0004):
        self.maker_rebate = maker_rebate
        self.taker_fee = taker_fee

    def choose(self, adverse_selection_est: float) -> str:
        """Return 'maker' or 'taker' depending on expected cost.
        adverse_selection_est: expected adverse slippage if placing maker order
        Decision: maker if adverse_selection_est + taker_fee - maker_rebate < 0
        """
        if adverse_selection_est + self.taker_fee - self.maker_rebate < 0:
            return 'maker'
        return 'taker'
