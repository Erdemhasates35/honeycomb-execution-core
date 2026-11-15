"""
Production FinRL Bridge for Honeycomb Execution Core

Real interface to FinRL-style environments and agents.
Does not fabricate market data or rewards.
Expects external data feed and real exchange connector.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

logger = logging.getLogger("honeycomb.finrl_bridge")


class MarketDataProvider(Protocol):
    def get_ohlcv(self, symbol: str, timeframe: str, limit: int) -> List[Dict[str, float]]: ...
    def get_balance(self) -> Dict[str, float]: ...


class OrderExecutor(Protocol):
    def place_order(self, symbol: str, side: str, quantity: float, order_type: str = "MARKET") -> Dict[str, Any]: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_positions(self) -> List[Dict[str, Any]]: ...


@dataclass
class ProductionFinRLConfig:
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT"])
    timeframe: str = "15m"
    max_position_pct: float = 0.25
    risk_per_trade: float = 0.01
    require_guard_approval: bool = True
    telemetry_enabled: bool = True


class ProductionFinRLBridge:
    """
    Production bridge. All market data and order actions must come from
    real providers. No internal random or synthetic generation.
    """

    def __init__(
        self,
        config: Optional[ProductionFinRLConfig] = None,
        data_provider: Optional[MarketDataProvider] = None,
        executor: Optional[OrderExecutor] = None,
        guard_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> None:
        self.config = config or ProductionFinRLConfig()
        self.data_provider = data_provider
        self.executor = executor
        self.guard_callback = guard_callback
        self._ready = data_provider is not None and executor is not None

    @property
    def is_ready(self) -> bool:
        return self._ready

    def observe(self, symbol: str) -> Dict[str, Any]:
        if not self.data_provider:
            raise RuntimeError("No MarketDataProvider attached — production mode forbids synthetic data")
        ohlcv = self.data_provider.get_ohlcv(symbol, self.config.timeframe, limit=100)
        balance = self.data_provider.get_balance()
        return {"ohlcv": ohlcv, "balance": balance, "symbol": symbol}

    def act(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if not self.executor:
            raise RuntimeError("No OrderExecutor attached")
        if self.config.require_guard_approval and self.guard_callback:
            approved = self.guard_callback(action)
            if not approved:
                logger.warning("Guard rejected action: %s", action)
                return {"status": "rejected_by_guard", "action": action}
        result = self.executor.place_order(
            symbol=action["symbol"],
            side=action["side"],
            quantity=float(action["quantity"]),
            order_type=action.get("order_type", "MARKET"),
        )
        return {"status": "submitted", "result": result}

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self.executor:
            return []
        return self.executor.get_positions()


def create_production_finrl_bridge(
    data_provider: MarketDataProvider,
    executor: OrderExecutor,
    guard_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> ProductionFinRLBridge:
    """Only create when real providers are supplied."""
    return ProductionFinRLBridge(
        data_provider=data_provider,
        executor=executor,
        guard_callback=guard_callback,
    )
