class FundingRateArbitrageMath:
    def __init__(self, taker_fee: float = 0.0005, estimated_slippage: float = 0.0003):
        self.taker_fee = taker_fee
        self.slippage = estimated_slippage
        self.total_friction = 2 * (self.taker_fee + self.slippage)

    def calculate_net_yield(self, spot_price: float, futures_price: float, funding_rate_8h: float, holding_periods: int) -> dict:
        """
        Calculates net arbitrage yield accounting for execution friction.
        """
        gross_funding_yield = funding_rate_8h * holding_periods
        price_spread = (futures_price - spot_price) / spot_price
        
        net_yield = gross_funding_yield + price_spread - self.total_friction
        is_viable = net_yield > 0
        
        return {
            "is_viable": is_viable,
            "gross_funding_yield_pct": gross_funding_yield * 100,
            "friction_cost_pct": self.total_friction * 100,
            "net_yield_pct": net_yield * 100,
            "annualized_roi_pct": (net_yield * (365 * 3 / holding_periods)) * 100
        }
