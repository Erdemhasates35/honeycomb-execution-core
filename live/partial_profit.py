"""Kernel sinifi silinmisse import buradan gelir. Emir burada yazilmaz."""
from __future__ import annotations
import threading
from typing import Any, Dict, Optional

class PartialProfitEngine:
    """
    Kademeli kısmi kâr alma: pozisyon TP'ye doğru ilerledikçe kalan
    miktarın bir kısmını GERÇEK PİYASA EMRİYLE kapatıp kârı realize
    eder, geri kalanı TP/SL korumasıyla çalışmaya devam eder. Mevcut
    kernel.close_market()/place_protect() metodları kullanılır (hiçbir
    emir/imza mantığı burada TEKRAR YAZILMADI).

    ÖNEMLİ: kernel.close_market() kendi içinde cancel_all() çağırıyor,
    bu da kalan pozisyonun TP/SL korumasını da siliyor — bu yüzden her
    kısmi kapatmadan sonra place_protect() ile koruma kalan miktar için
    YENİDEN kuruluyor (closePosition=true tipi emirler zaten miktar
    belirtmez, kalan ne kadarsa onu kapatır).

    Varsayılan: TP mesafesinin %50'sinde kalanın %35'i, %80'inde yine
    kalanın %35'i realize edilir — pozisyonun tamamı tek bir TP
    seviyesine bağlı kalmaz, "az kârda erken kapat, potansiyeli tamamen
    kaçırma" dengesini kurar.
    """
    DEFAULT_STAGES = [(0.50, 0.35), (0.80, 0.35)]  # (ilerleme, kalanın kapatılacak yüzdesi)

    def __init__(self, kernel, stages=None, log_fn=None):
        self.kernel = kernel
        self.stages = stages or self.DEFAULT_STAGES
        self.log = log_fn or (lambda m: None)
        self._pos: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, symbol, side, entry, tp, sl, qty, pos_side=None):
        with self._lock:
            self._pos[symbol] = {
                "side": side, "entry": entry, "tp": tp, "sl": sl,
                "qty_remaining": qty, "stage": 0, "pos_side": pos_side,
                "realized_net": 0.0,
            }

    def forget(self, symbol):
        with self._lock:
            return self._pos.pop(symbol, None)

    def get(self, symbol) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._pos[symbol]) if symbol in self._pos else None

    def update(self, symbol, current_price) -> Optional[Dict[str, Any]]:
        with self._lock:
            pos = self._pos.get(symbol)
        if not pos or pos["qty_remaining"] <= 0 or pos["stage"] >= len(self.stages):
            return None
        entry, side, tp = pos["entry"], pos["side"], pos["tp"]
        dist = abs(tp - entry)
        if dist <= 0:
            return None
        progress = (current_price - entry) / dist if side == "LONG" else (entry - current_price) / dist
        thresh, close_frac = self.stages[pos["stage"]]
        if progress < thresh:
            return None

        close_qty = pos["qty_remaining"] * close_frac
        try:
            fill = self.kernel.close_market(symbol, side, close_qty, pos.get("pos_side"))
            net = float(fill.get("rp", 0.0)) - float(fill.get("commission", 0.0))
            with self._lock:
                if symbol not in self._pos:
                    return None
                self._pos[symbol]["qty_remaining"] = max(0.0, self._pos[symbol]["qty_remaining"] - fill["qty"])
                self._pos[symbol]["stage"] += 1
                self._pos[symbol]["realized_net"] += net
                remaining = self._pos[symbol]["qty_remaining"]
                stage_done = self._pos[symbol]["stage"]
            if remaining > 0:
                self.kernel.place_protect(symbol, side, entry, tp, pos["sl"], pos.get("pos_side"))
            self.log(
                f"KISMI KAR AL {side} {symbol} | ilerleme={progress*100:.0f}% | kapatılan={fill['qty']:.6g} "
                f"(kademe {stage_done}/{len(self.stages)}) | net={net:+.4f} | kalan={remaining:.6g}"
            )
            return {"qty_closed": fill["qty"], "net": net, "remaining": remaining, "stage": stage_done}
        except Exception as e:
            self.log(f"KISMI KAR AL HATA {symbol}: {e}")
            return None
