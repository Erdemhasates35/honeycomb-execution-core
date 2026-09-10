import math
import sys
import time
import json
import urllib.request
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any

# ==============================================================================
# 1. KATMAN: SAF MATEMATİK VE İSTATİSTİK MOTORU (Zero-Dependency Math Core)
# ==============================================================================

class PureMathEngine:
    @staticmethod
    def mean(data: List[float]) -> float:
        return sum(data) / len(data) if data else 0.0

    @staticmethod
    def std_dev(data: List[float], mean_val: float = None) -> float:
        if len(data) < 2:
            return 0.0
        if mean_val is None:
            mean_val = PureMathEngine.mean(data)
        variance = sum((x - mean_val) ** 2 for x in data) / (len(data) - 1)
        return math.sqrt(variance)

    @staticmethod
    def ols_regression(y: List[float], x: List[float]) -> Tuple[float, float, List[float]]:
        n = len(x)
        if n != len(y) or n < 2:
            raise ValueError("Veri boyutları eşit ve en az 2 olmalıdır.")

        x_mean = PureMathEngine.mean(x)
        y_mean = PureMathEngine.mean(y)

        num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        den = sum((x[i] - x_mean) ** 2 for i in range(n))

        gamma = num / den if den != 0 else 0.0
        alpha = y_mean - gamma * x_mean
        residuals = [y[i] - (gamma * x[i] + alpha) for i in range(n)]

        return gamma, alpha, residuals

    @staticmethod
    def adf_test_approximation(residuals: List[float]) -> Tuple[float, float]:
        n = len(residuals)
        if n < 3:
            return 0.0, 1.0

        delta_e = [residuals[i] - residuals[i-1] for i in range(1, n)]
        e_lag = residuals[:-1]

        phi, _, errors = PureMathEngine.ols_regression(delta_e, e_lag)
        
        sum_e_sq = sum(x**2 for x in e_lag)
        se_phi = PureMathEngine.std_dev(errors) / math.sqrt(sum_e_sq) if sum_e_sq > 0 else 1.0
        t_stat = phi / se_phi if se_phi > 0 else 0.0

        if t_stat < -3.5:
            p_val = 0.01
        elif t_stat < -2.9:
            p_val = 0.04
        elif t_stat < -2.6:
            p_val = 0.08
        else:
            p_val = 0.50

        return t_stat, p_val

    @staticmethod
    def calculate_z_score(residuals: List[float], window: int) -> float:
        if len(residuals) < window:
            return 0.0
        sub_series = residuals[-window:]
        m = PureMathEngine.mean(sub_series)
        s = PureMathEngine.std_dev(sub_series, m)
        return (residuals[-1] - m) / s if s > 0 else 0.0


# ==============================================================================
# 2. KATMAN: FONLAMA ORANI VE SÜRTÜNME MALİYETİ BİLÇİLEYİCİSİ
# ==============================================================================

class FundingRateMath:
    def __init__(self, taker_fee: float = 0.0005, estimated_slippage: float = 0.0003):
        self.taker_fee = taker_fee
        self.slippage = estimated_slippage
        self.total_friction = 2 * (self.taker_fee + self.slippage)

    def calculate_net_yield(self, spot_price: float, futures_price: float, funding_rate_8h: float, holding_periods: int) -> Dict[str, Any]:
        gross_funding_yield = funding_rate_8h * holding_periods
        price_spread = (futures_price - spot_price) / spot_price if spot_price > 0 else 0
        
        net_yield = gross_funding_yield + price_spread - self.total_friction
        
        return {
            "is_viable": net_yield > 0,
            "gross_funding_yield_pct": gross_funding_yield * 100,
            "friction_cost_pct": self.total_friction * 100,
            "net_yield_pct": net_yield * 100,
            "annualized_roi_pct": (net_yield * (365 * 3 / max(holding_periods, 1))) * 100
        }


# ==============================================================================
# 3. KATMAN: ASKERİ DİSİPLİNLİ RİSK VE DEVRE KESİCİ
# ==============================================================================

class MilitaryCircuitBreaker:
    def __init__(self, max_drawdown_limit: float = 0.03, max_exposure_usdt: float = 5000.0):
        self.max_dd = max_drawdown_limit
        self.max_exposure = max_exposure_usdt

    def evaluate_risk(self, current_equity: float, peak_equity: float, current_exposure: float) -> bool:
        if peak_equity <= 0:
            return True
            
        drawdown = (peak_equity - current_equity) / peak_equity
        if drawdown >= self.max_dd or current_exposure > self.max_exposure:
            return False
        return True


# ==============================================================================
# 4. KATMAN: BİNANCE AĞ ARAYÜZÜ VE EMİR GATEWAY
# ==============================================================================

@dataclass
class OrderPayload:
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float

class BinanceDirectGateway:
    def execute_order(self, order: OrderPayload) -> bool:
        print(f">> [EMİR İLETİLDİ]: {order.symbol} | Yön: {order.side} | Tip: {order.order_type} | Miktar: {order.quantity} | Fiyat: {order.price}")
        return True


# ==============================================================================
# 5. KATMAN: AŞILAMAZ BÜTÜNLEŞİK KONTROLÖR (PARETO 80/20 CORE)
# ==============================================================================

class AutonomousQuantEngine:
    def __init__(self):
        self.math = PureMathEngine()
        self.funding = FundingRateMath()
        self.circuit_breaker = MilitaryCircuitBreaker()
        self.gateway = BinanceDirectGateway()

    def run_engine_cycle(self, series_a: List[float], series_b: List[float], spot_p: float, fut_p: float):
        print("\n--- OTONOM KANTİTATİF MOTOR ÇALIŞMA DÖNGÜSÜ BAŞLATILDI ---")
        
        gamma, alpha, residuals = self.math.ols_regression(series_a, series_b)
        t_stat, p_val = self.math.adf_test_approximation(residuals)
        is_cointegrated = p_val < 0.05
        z_score = self.math.calculate_z_score(residuals, window=10)

        yield_eval = self.funding.calculate_net_yield(
            spot_price=spot_p, 
            futures_price=fut_p, 
            funding_rate_8h=0.001, 
            holding_periods=3
        )

        risk_ok = self.circuit_breaker.evaluate_risk(current_equity=10000.0, peak_equity=10000.0, current_exposure=1500.0)

        print(f"Eşbütünleşme Durumu   : {'EVET' if is_cointegrated else 'HAYIR'} (p-değeri: {p_val:.4f})")
        print(f"Hesaplanan Hedge Oranı : {gamma:.4f}")
        print(f"Anlık Z-Score          : {z_score:.4f}")
        print(f"Net Getiri Beklentisi  : %{yield_eval['net_yield_pct']:.3f} (Yıllık: %{yield_eval['annualized_roi_pct']:.1f})")
        print(f"Sistem Risk Onayı      : {'ONAYLANDI' if risk_ok else 'REDDEDİLDİ'}")

        # Çift Yönlü İstatistiksel Arbitraj Tetikleyicisi
        if is_cointegrated and yield_eval['is_viable'] and risk_ok:
            if z_score > 2.0:
                print(">> [SİNYAL ONAYLANDI]: Aşırı Değerlenme Tespiti (Short Arbitraj).")
                order = OrderPayload(symbol="BTCUSDT", side="SELL", order_type="LIMIT", quantity=0.01, price=fut_p)
                self.gateway.execute_order(order)
            elif z_score < -2.0:
                print(">> [SİNYAL ONAYLANDI]: Düşük Değerlenme Tespiti (Long Arbitraj).")
                order = OrderPayload(symbol="BTCUSDT", side="BUY", order_type="LIMIT", quantity=0.01, price=fut_p)
                self.gateway.execute_order(order)
            else:
                print(">> [SİNYAL PASİF]: Z-Score eşik değer aralığında (-2.0 < Z < 2.0). Pozisyon alınmadı.")
        else:
            print(">> [SİNYAL PASİF]: Temel arbitraj şartları sağlanmadı.")

if __name__ == "__main__":
    engine = AutonomousQuantEngine()
    
    # Test Verisi (Z-Score > 2.0 üretip pozisyon tetikleme simülasyonu)
    mock_series_b = [100.0 + i * 0.1 for i in range(50)]
    mock_series_a = [b * 1.5 + (3.5 if i >= 45 else 0.1) for i, b in enumerate(mock_series_b)]

    engine.run_engine_cycle(
        series_a=mock_series_a, 
        series_b=mock_series_b, 
        spot_p=100.0, 
        fut_p=100.8
    )
