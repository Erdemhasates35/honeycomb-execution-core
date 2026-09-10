import time
import numpy as np
from cointegration_engine import CointegrationTruthEngine
from funding_math import FundingRateArbitrageMath
from circuit_breaker import MilitaryCircuitBreaker

def run_production_loop():
    coint_engine = CointegrationTruthEngine(entry_z_score=2.0, exit_z_score=0.5)
    funding_math = FundingRateArbitrageMath(taker_fee=0.0005, estimated_slippage=0.0003)
    risk_breaker = MilitaryCircuitBreaker(max_drawdown_limit=0.03, max_exposure_usdt=5000.0)

    peak_equity = 10000.0
    current_equity = 10000.0
    current_exposure = 2000.0

    print("[CORE ENGINE INITIALIZED]: Quant Lab Autonomous Loop Active.")

    for cycle in range(5):
        if not risk_breaker.evaluate_risk(current_equity, peak_equity, current_exposure):
            break

        series_a = np.random.normal(100, 2, 100)
        series_b = series_a * 1.5 + np.random.normal(0, 0.5, 100)

        is_coint, gamma, p_val = coint_engine.verify_cointegration(series_a, series_b)
        
        if is_coint:
            residuals = series_a - gamma * series_b
            z_scores = coint_engine.calculate_z_score_fast(residuals, window=20)
            latest_z = z_scores[-1]

            yield_info = funding_math.calculate_net_yield(
                spot_price=100.0, 
                futures_price=100.5, 
                funding_rate_8h=0.001, 
                holding_periods=3
            )

            print(f"Cycle {cycle+1} | Cointegrated: YES (p={p_val:.4f}) | Z-Score: {latest_z:.2f} | Net Yield: {yield_info['net_yield_pct']:.3f}%")
        else:
            print(f"Cycle {cycle+1} | Cointegrated: NO (p={p_val:.4f}) - Skipping Trade.")

        time.sleep(0.5)

if __name__ == "__main__":
    run_production_loop()
