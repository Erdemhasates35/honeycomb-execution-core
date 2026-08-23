# python_engine/engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time
import uuid

from python_engine.idempotency import IdempotencySQLite

@dataclass
class RiskEngine:
    live_max_capital_percent: float = 10.0  # percent
    max_leverage: int = 50

    def calculate_max_notional(self, account_equity: float) -> float:
        if account_equity <= 0:
            return 0.0
        pct = max(0.0, min(self.live_max_capital_percent, 100.0))
        return account_equity * (pct / 100.0)

    def enforce_leverage(self, requested: int) -> int:
        if requested is None:
            requested = 1
        try:
            r = int(requested)
        except Exception:
            r = 1
        if r < 1:
            r = 1
        if r > self.max_leverage:
            return self.max_leverage
        return r

    def kelly_fraction(self, win_prob: float, win_loss_ratio: float, shrink: float = 1.0) -> float:
        # Kelly f* = (p*(b+1) -1)/b where b = win_loss_ratio
        if win_loss_ratio <= 0:
            return 0.0
        p = max(0.0, min(1.0, win_prob))
        b = win_loss_ratio
        f = (p * (b + 1) - 1) / b
        f = max(0.0, f) * float(shrink)
        return f

class ExecutionGateway:
    def send_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_account(self) -> Dict[str, Any]:
        raise NotImplementedError

    def fetch_positions(self) -> Dict[str, Any]:
        raise NotImplementedError

class OrderEngine:
    def __init__(self, gateway: ExecutionGateway, risk: RiskEngine, idempotency_db: str = ':memory:'):
        self.gateway = gateway
        self.risk = risk
        self.idempotency = IdempotencySQLite(idempotency_db)

    def create_client_order_id(self, prefix: str = "hc") -> str:
        return f"{prefix}-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"

    def can_open_notional(self, account_equity: float, requested_notional: float) -> bool:
        max_notional = self.risk.calculate_max_notional(account_equity)
        return requested_notional <= max_notional

    def prepare_order(self, symbol: str, side: str, notional: float, requested_leverage: int, account_equity: float) -> Dict[str, Any]:
        if not self.can_open_notional(account_equity, notional):
            raise ValueError("capital_limit_exceeded")
        eff_lev = self.risk.enforce_leverage(requested_leverage)
        client_id = self.create_client_order_id()
        order = {
            "client_order_id": client_id,
            "symbol": symbol,
            "side": side,
            "notional": notional,
            "leverage": eff_lev,
            "timestamp": int(time.time()*1000),
        }
        return order

    def send(self, order: Dict[str, Any]) -> Dict[str, Any]:
        cid = order.get("client_order_id")
        stored = self.idempotency.get(cid)
        if stored:
            return stored
        res = self.gateway.send_order(order)
        self.idempotency.put(cid, res)
        return res

# Simple in-memory mock gateway for tests
class MockGateway(ExecutionGateway):
    def __init__(self, account_equity: float = 1000.0):
        self._account_equity = account_equity
        self.sent_orders = []

    def send_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        res = {"orderId": int(time.time()*1000), "clientOrderId": order.get("client_order_id"), "status": "FILLED", "avgPrice": 1.0}
        self.sent_orders.append(order)
        return res

    def fetch_account(self) -> Dict[str, Any]:
        return {"equity": self._account_equity}

    def fetch_positions(self) -> Dict[str, Any]:
        return {}
