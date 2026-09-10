import numpy as np
import pandas as pd
#from numba
import jit
#import statsmodels.tsa.stattools as ts

class CointegrationTruthEngine:
    def __init__(self, entry_z_score: float = 2.0, exit_z_score: float = 0.5):
        self.entry_z = entry_z_score
        self.exit_z = exit_z_score

    def verify_cointegration(self, series_a: np.ndarray, series_b: np.ndarray) -> tuple[bool, float, float]:
        """
        Engle-Granger 2-Step Cointegration Test.
        Returns: (is_cointegrated, hedge_ratio/gamma, p_value)
        """
        matrix = np.vstack([series_b, np.ones(len(series_b))]).T
        gamma, alpha = np.linalg.lstsq(matrix, series_a, rcond=None)[0]
        
        residuals = series_a - (gamma * series_b + alpha)
        adf_result = ts.adfuller(residuals, maxlag=1)
        p_value = adf_result[1]
        
        is_cointegrated = p_value < 0.05
        return is_cointegrated, gamma, p_value

    @staticmethod
    @jit(nopython=True, fastmath=True)
    def calculate_z_score_fast(residuals: np.ndarray, window: int) -> np.ndarray:
        """
        Numba JIT optimized rolling Z-Score calculation for sub-millisecond execution.
        """
        n = len(residuals)
        z_scores = np.zeros(n)
        for i in range(window, n):
            sub = residuals[i - window : i]
            mean = np.mean(sub)
            std = np.std(sub)
            if std > 0:
                z_scores[i] = (residuals[i] - mean) / std
            else:
                z_scores[i] = 0.0
        return z_scores
