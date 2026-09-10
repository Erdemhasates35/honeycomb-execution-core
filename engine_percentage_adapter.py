#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from percentage_economics import TradeEconomics, approval


def evaluate_engine(
    stats: TradeEconomics,
    *,
    current_entry_fee_pct: float,
    current_exit_fee_pct: float,
    current_spread_pct: float,
    current_slippage_pct: float,
    current_funding_pct: float,
    current_impact_pct: float,
) -> dict:

    current_cost_pct = (
        float(current_entry_fee_pct)
        + float(current_exit_fee_pct)
        + float(current_spread_pct)
        + float(current_slippage_pct)
        + float(current_funding_pct)
        + float(current_impact_pct)
    )

    expected_net_after_current_cost_pct = (
        stats.expected_net_pct
        - current_cost_pct
        + stats.avg_total_cost_pct
    )

    return {
        "historical": {
            "n": stats.n,
            "win_probability_pct": stats.win_probability_pct,
            "loss_probability_pct": stats.loss_probability_pct,
            "avg_gross_win_pct": stats.avg_gross_win_pct,
            "avg_gross_loss_pct": stats.avg_gross_loss_pct,
            "avg_total_cost_pct": stats.avg_total_cost_pct,
            "avg_net_win_pct": stats.avg_net_win_pct,
            "avg_net_loss_pct": stats.avg_net_loss_pct,
            "expected_net_pct": stats.expected_net_pct,
            "profit_factor": stats.profit_factor,
            "break_even_win_probability_pct":
                stats.break_even_win_probability_pct,
        },
        "current_cost_pct": current_cost_pct,
        "expected_net_after_current_cost_pct":
            expected_net_after_current_cost_pct,
        "economic_approval": (
            approval(stats)
            and expected_net_after_current_cost_pct > 0.0
        ),
    }
