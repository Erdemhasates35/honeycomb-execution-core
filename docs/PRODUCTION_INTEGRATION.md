# Production Integration Status — Honeycomb Execution Core

## Modules added (2026-11-15)

- `src/production/ara_adapter.py`  
  Real Arbitrary-Rank Ablation LoRA adapter. Initializes only from real base weights. No synthetic activations. Row-norm preservation included.

- `src/production/finrl_bridge.py`  
  Production FinRL-style bridge. Requires real `MarketDataProvider` and `OrderExecutor`. Guard callback mandatory by default. No internal market-data generation.

## Design invariants (non-negotiable)

1. No Math.random / synthetic OHLCV / fake PnL.
2. Every order path must pass Guard (if configured).
3. ARA adapter never invents features; it only transforms real weights.
4. Telemetry must carry source timestamp + event id when enabled.

## Usage contract

```python
from src.production import create_production_ara_adapter, create_production_finrl_bridge

ara = create_production_ara_adapter(rank=16)
ara.initialize_from_base(real_base_weight)  # must be real Tensor

bridge = create_production_finrl_bridge(
    data_provider=real_binance_provider,
    executor=real_order_executor,
    guard_callback=guard_fn,
)
assert bridge.is_ready
```

## Next required wiring (operator action)

- Attach live Binance/Bitget provider implementing the Protocol.
- Attach real Guard decision service.
- Load ARA state from verified checkpoint if continuing previous ablation.

This file is the canonical production status for the execution layer.
