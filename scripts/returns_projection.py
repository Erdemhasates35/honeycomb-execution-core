#!/usr/bin/env python3
"""Scenario model for 1000 TL starting capital.

This is an expected-value model, not a return guarantee. It makes every
assumption explicit so live performance can be compared with the model.
"""
from __future__ import annotations

import argparse
from decimal import Decimal as D


def money(v):
    return f"{v:,.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital-tl", type=D, default=D("1000"))
    ap.add_argument("--usdtry", type=D, default=D("48.04"))
    ap.add_argument("--risk-pct", type=D, default=D("0.75"))
    ap.add_argument("--tp-pct", type=D, default=D("0.80"))
    ap.add_argument("--sl-pct", type=D, default=D("0.80"))
    ap.add_argument("--cost-pct", type=D, default=D("0.095"))
    ap.add_argument("--buffer-pct", type=D, default=D("0.10"))
    ap.add_argument("--trades-day", type=int, nargs="+", default=[6, 12, 24])
    args = ap.parse_args()

    capital_usdt = args.capital_tl / args.usdtry
    effective_risk_pct = args.sl_pct + args.cost_pct + args.buffer_pct
    notional_factor = args.risk_pct / effective_risk_pct
    notional_usdt = capital_usdt * notional_factor

    print(f"capital: {money(args.capital_tl)} TL = {capital_usdt:.4f} USDT")
    print(f"risk/trade: {args.risk_pct}% | TP: {args.tp_pct}% | SL: {args.sl_pct}% | total cost: {args.cost_pct}% | buffer: {args.buffer_pct}%")
    print(f"risk-based notional: {notional_usdt:.4f} USDT")
    print()

    for wr in (D("0.52"), D("0.60"), D("0.65"), D("0.70")):
        edge_pct_notional = (D("2") * wr - D("1")) * args.tp_pct - args.cost_pct
        edge_fraction_equity = (edge_pct_notional * notional_factor) / D("100")
        print(f"WIN RATE {wr * 100:.0f}% | EV/trade={edge_pct_notional:.4f}% notional | EV/trade={edge_fraction_equity * 100:.4f}% equity")
        for n in args.trades_day:
            daily = (D("1") + edge_fraction_equity) ** n - D("1")
            weekly = (D("1") + edge_fraction_equity) ** (n * 7) - D("1")
            monthly = (D("1") + edge_fraction_equity) ** (n * 30) - D("1")
            print(f"  {n:>2} trades/day: day {daily*100:.2f}% | week {weekly*100:.2f}% | 30d {monthly*100:.2f}% | 30d balance {money(args.capital_tl*(D('1')+edge_fraction_equity)**(n*30))} TL")
        print()


if __name__ == "__main__":
    main()
