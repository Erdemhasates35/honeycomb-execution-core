from __future__ import annotations
import time
import functools

_FAIL_COUNTS = {}
_CIRCUIT_UNTIL = {}
_RANK_CACHE_BUST = 0

def _fmt_price(self, symbol, price):
    try:
        tick = self.filters.get(symbol, {}).get("tickSize", 0.0001)
    except Exception:
        tick = 0.0001
    if tick <= 0:
        return round(float(price), 4)
    steps = round(float(price) / tick)
    return round(steps * tick, 8)

def _resilient_call(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        key = fn.__name__ + ":" + str(args[:1])
        now = time.time()
        until = _CIRCUIT_UNTIL.get(key, 0)
        if now < until:
            raise RuntimeError(f"circuit-open {key} until {until - now:.1f}s")
        try:
            result = fn(self, *args, **kwargs)
            _FAIL_COUNTS[key] = 0
            return result
        except Exception as e:
            n = _FAIL_COUNTS.get(key, 0) + 1
            _FAIL_COUNTS[key] = n
            backoff = min(300, 2 ** min(n, 8))
            _CIRCUIT_UNTIL[key] = now + backoff
            raise
    return wrapper

def apply_patches(kernel_cls):
    if not hasattr(kernel_cls, "_fmt_price"):
        kernel_cls._fmt_price = _fmt_price
    for name in ("margin", "set_margin_type", "open_position", "protect_take_profit", "protect_stop"):
        if hasattr(kernel_cls, name):
            orig = getattr(kernel_cls, name)
            if not getattr(orig, "_patched", False):
                patched = _resilient_call(orig)
                patched._patched = True
                setattr(kernel_cls, name, patched)
    return kernel_cls

def safe_dict(x):
    if isinstance(x, dict):
        return x
    if isinstance(x, (tuple, list)):
        return {"price": x[0] if len(x) > 0 else None, "qty": x[1] if len(x) > 1 else None}
    return {}

_MARGIN_SET = set()

def margin_once(kernel_self, symbol, margin_fn, margin_type="ISOLATED"):
    if symbol in _MARGIN_SET:
        return True
    try:
        margin_fn(symbol, margin_type)
        _MARGIN_SET.add(symbol)
        return True
    except Exception as e:
        _MARGIN_SET.add(symbol)
        return False

_MARGIN_SET = set()

def margin_once(kernel_self, symbol, margin_fn, margin_type="ISOLATED"):
    if symbol in _MARGIN_SET:
        return True
    try:
        margin_fn(symbol, margin_type)
        _MARGIN_SET.add(symbol)
        return True
    except Exception as e:
        _MARGIN_SET.add(symbol)
        return False
