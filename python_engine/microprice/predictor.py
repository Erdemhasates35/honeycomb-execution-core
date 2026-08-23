# python_engine/microprice/predictor.py
"""Microprice based short-term decision helper.
"""
from typing import Dict, Any

class MicroPrice:
    @staticmethod
    def microprice(bid: float, bid_size: float, ask: float, ask_size: float) -> float:
        denom = ask_size + bid_size
        if denom == 0:
            return (bid + ask) / 2.0
        return (bid*ask_size + ask*bid_size) / denom

    @staticmethod
    def should_take(micro_now: float, micro_future_est: float, threshold: float = 0.0005) -> bool:
        return (micro_future_est - micro_now) > threshold
