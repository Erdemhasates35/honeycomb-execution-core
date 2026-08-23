# python_engine/market_maker/mm.py
"""Simplified HFT market-making inventory controller.
"""
from typing import Dict, Any

class InventoryController:
    def __init__(self, target_inventory: float = 0.0, kappa: float = 0.1):
        self.target_inventory = target_inventory
        self.kappa = kappa

    def inventory_adjustment(self, current_inventory: float) -> float:
        # returns skew adjustment factor
        return self.kappa * (self.target_inventory - current_inventory)

class MarketMaker:
    def __init__(self, spread: float = 0.1):
        self.spread = spread

    def quote(self, mid_price: float, inventory_adj: float) -> Dict[str, float]:
        bid = mid_price - (self.spread/2.0) + inventory_adj
        ask = mid_price + (self.spread/2.0) + inventory_adj
        return {'bid': bid, 'ask': ask}
