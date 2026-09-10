from __future__ import annotations
import math

def round_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    precision = max(0, len(str(step).split(".")[-1].rstrip("0")))
    return math.floor(qty / step) * step

def safe_qty(price: float, target_qty: float, step_size: float, min_notional: float, min_qty: float) -> float:
    qty = round_step(target_qty, step_size)
    if qty * price < min_notional:
        needed = min_notional / price
        qty = math.ceil(needed / step_size) * step_size
    if qty < min_qty:
        qty = math.ceil(min_qty / step_size) * step_size
    return round(qty, 10)

def protect_params(side: str, close_position: bool, quantity: float, price: float, stop_price: float) -> dict:
    p = {
        "side": side,
        "type": "STOP_MARKET",
        "stopPrice": price,
        "workingType": "MARK_PRICE",
        "reduceOnly": "true",
    }
    if close_position:
        p["closePosition"] = "true"
    else:
        p["quantity"] = quantity
    return p
