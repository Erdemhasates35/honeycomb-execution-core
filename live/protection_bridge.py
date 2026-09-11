from __future__ import annotations

import math
import time
import uuid
from typing import Any


def _kernel_class(args: tuple[Any, ...], kwargs: dict[str, Any]):
    cls = kwargs.get("LiveKernel") or kwargs.get("kernel_class")
    if cls is not None:
        return cls
    for arg in args:
        if isinstance(arg, type) and arg.__name__ == "LiveKernel":
            return arg
    try:
        from live.kernel import LiveKernel
        return LiveKernel
    except Exception:
        return None


def _venue(kernel) -> str:
    return str(getattr(kernel, "venue", "usdt")).lower()


def _algo_endpoint(kernel) -> str:
    return "/dapi/v1/algoOrder" if _venue(kernel) in ("coin", "coinm", "dapi") else "/fapi/v1/algoOrder"


def _algo_open_endpoint(kernel) -> str:
    return "/dapi/v1/openAlgoOrders" if _venue(kernel) in ("coin", "coinm", "dapi") else "/fapi/v1/openAlgoOrders"


def _algo_cancel_endpoint(kernel) -> str:
    return "/dapi/v1/algoOpenOrders" if _venue(kernel) in ("coin", "coinm", "dapi") else "/fapi/v1/algoOpenOrders"


def _position_mode(kernel):
    try:
        value = kernel.position_mode()
    except Exception:
        return None
    if isinstance(value, str):
        v = value.upper()
        if v in ("HEDGE", "DUAL", "DUAL_SIDE", "TRUE"): return True
        if v in ("ONE_WAY", "BOTH", "SINGLE", "FALSE"): return False
    return bool(value) if isinstance(value, bool) else None


def _price(kernel, symbol: str, value: float) -> str:
    try:
        tick = float(kernel.get_filters(symbol).get("tickSize") or 0)
        if tick > 0:
            decimals = max(0, min(12, len(("%.12f" % tick).rstrip("0").split(".")[-1])))
            value = math.floor(value / tick) * tick
            return ("%%.%df" % decimals) % value
    except Exception:
        pass
    return ("%.8f" % float(value)).rstrip("0").rstrip(".")


def _protect(self, symbol, side, entry, tp=None, sl=None, position_side=None, **kwargs):
    symbol = str(symbol).upper()
    side = str(side).upper()
    if tp is None and sl is None: return []
    close_side = "SELL" if side in ("BUY", "LONG") else "BUY"
    hedge = _position_mode(self)
    position_side = position_side or kwargs.get("positionSide")
    if hedge is True and position_side is None:
        position_side = "LONG" if side in ("BUY", "LONG") else "SHORT"
    if hedge is False: position_side = None
    results=[]; failures=[]
    for label, trigger, algo_type in (("TAKE_PROFIT_MARKET",tp,"TAKE_PROFIT_MARKET"),("STOP_MARKET",sl,"STOP_MARKET")):
        if trigger is None: continue
        try:
            trigger_f=float(trigger)
            if not trigger_f>0: raise ValueError("invalid trigger price")
            offset_ms=getattr(self,"_off",None)
            if offset_ms is None: offset_ms=int(float(getattr(self,"time_offset",0.0) or 0.0)*1000)
            params={"symbol":symbol,"side":close_side,"type":algo_type,"algoType":"CONDITIONAL","triggerPrice":_price(self,symbol,trigger_f),"workingType":"MARK_PRICE","closePosition":"true","clientAlgoId":"HC_"+label[:3]+"_"+uuid.uuid4().hex[:20],"timestamp":int(time.time()*1000)+int(offset_ms),"recvWindow":10000}
            if position_side is not None: params["positionSide"]=position_side
            res=self._http("POST",_algo_endpoint(self),params,signed=True,weight=1,is_order=True)
            self.log("ALGO PROTECT %s %s trigger=%s result=%s"%(symbol,label,params["triggerPrice"],res)); results.append(res)
        except Exception as exc:
            failures.append((label,repr(exc))); self.log("ALGO PROTECT FAIL %s %s: %s"%(symbol,label,exc))
    if failures: self.log("ALGO PROTECT INCOMPLETE %s failures=%s"%(symbol,failures))
    return results


def _query_open_algo(self, symbol=None):
    offset_ms=getattr(self,"_off",None)
    if offset_ms is None: offset_ms=int(float(getattr(self,"time_offset",0.0) or 0.0)*1000)
    params={"timestamp":int(time.time()*1000)+int(offset_ms),"recvWindow":10000}
    if symbol: params["symbol"]=str(symbol).upper()
    return self._http("GET",_algo_open_endpoint(self),params,signed=True,weight=1,is_order=False)


def install(*args, **kwargs):
    cls=_kernel_class(args,kwargs)
    if cls is None: raise RuntimeError("LiveKernel class not available for protection bridge")
    cls.place_protect=_protect
    cls.open_algo_orders=_query_open_algo
    cls.get_open_algo_orders=_query_open_algo
    cls.openAlgoOrders=_query_open_algo
    return cls

try:
    from live.kernel import LiveKernel as _LK
except Exception:
    _LK=None
if _LK is not None: install(_LK)
