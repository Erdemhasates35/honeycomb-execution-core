# Quantitative strategy library

The strategy library contains ten independently testable quantitative components.

| Component | Function | Operational dependency |
|---|---|---|
| Basis and funding velocity | Funding/basis alignment, funding acceleration, net edge after estimated costs | Live mark/index/funding feed and ATR |
| ATR volatility | True range, trend regime and volatility-scaled protection | Historical OHLC candles |
| VWAP execution | Volume-weighted benchmark and participation-capped slicing plan | Time-bucketed trade volume and a slice scheduler |
| Correlation relative value | Rolling correlation, hedge ratio and spread z-score | Synchronized multi-instrument histories and paired execution |
| Order-book LSTM | Validated LSTM inference over depth, spread, microprice and trade-imbalance features | Signed model artifact and model-registry validation |
| Avellaneda–Stoikov | Inventory-adjusted reservation price and optimal quote spread | Limit-order placement and inventory reconciliation |
| Hawkes toxic flow | Buy/sell event intensity and toxicity gate | Timestamped trade stream |
| Cross-venue basis | Net executable edge after fees, slippage and latency penalty | Two independently healthy venue feeds and coordinated hedge execution |
| Fractional Kelly | Drawdown-scaled capital fraction from observed return distribution | Sufficient reconciled realized-return history |
| Event-sourced reconciliation | Exchange cumulative quantity versus unique trade events, fees and realized PnL | Exchange order and user-trade records |

These functions calculate signals, execution plans, quotes, sizing fractions or reconciliation results. They do not independently submit orders. Strategy activation remains controlled by the Supabase strategy catalog, validated strategy version, risk profile and execution router.

The LSTM module performs inference only. It does not contain fabricated weights or claim a trained model. It rejects malformed artifacts and must remain disabled until a signed model artifact has been trained on real market observations, validated out of sample and registered with its hash.

VWAP slicing, market making and cross-venue basis require execution capabilities beyond a single market-order path. Their mathematical components are implemented, but they must remain disabled until the relevant order types, paired-leg atomicity, cancel/replace lifecycle and reconciliation are integrated and tested on the target venue.
