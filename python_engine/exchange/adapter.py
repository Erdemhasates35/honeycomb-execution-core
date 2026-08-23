# python_engine/exchange/adapter.py
from typing import Tuple
from decimal import Decimal, ROUND_DOWN, getcontext
import math

getcontext().prec = 18

def round_to_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    q = Decimal(str(value))
    s = Decimal(str(step))
    r = (q // s) * s
    return float(r)

def round_price(price: float, tick: float) -> float:
    if tick <= 0:
        return float(price)
    q = Decimal(str(price))
    t = Decimal(str(tick))
    r = (q // t) * t
    return float(r)

def normalize_quantity(qty: float, step: float, min_qty: float) -> float:
    r = round_to_step(qty, step)
    if r < min_qty:
        return 0.0
    return r

def normalize_price(price: float, tick: float) -> float:
    return round_price(price, tick)
