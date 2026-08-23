# python_engine/tca/tca.py
"""Transaction Cost Analysis skeleton: models slippage based on simple linear model and records observations.
"""
from typing import List, Dict, Any

class TCA:
    def __init__(self):
        self.observations: List[Dict[str, Any]] = []

    def record(self, size: float, predicted_slippage: float, realized_slippage: float):
        self.observations.append({'size': size, 'predicted': predicted_slippage, 'realized': realized_slippage})

    def predict(self, size: float) -> float:
        # naive: average realized/predicted ratio applied
        if not self.observations:
            return 0.0
        avg = sum(o['realized'] for o in self.observations) / len(self.observations)
        return avg * (size / max(1.0, sum(o['size'] for o in self.observations)/len(self.observations)))
