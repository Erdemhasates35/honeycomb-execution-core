# LIVE Engine Map (Honeycomb Execution Core)

## Runtime contract
```
HONEYCOMB_MODE=LIVE
EXECUTION_MODE=live
LIVE_ARMED=1
BINANCE_BASE_URL=https://fapi.binance.com
MAX_LEVERAGE=50
LIVE_MAX_CAPITAL_PERCENT=10
HONEYCOMB_LOCK_PATH=$HOME/.honeycomb/sf.lock
```

## Emir zinciri
Signal → ModeGuard → PortfolioRisk ×3 → ExecutionGateway → live/kernel.py LiveKernel → Binance Futures HMAC → ACK/FILL

## Primary motors
| Motor | Dosya | Komut | Tetik |
|---|---|---|---|
| LiveKernel | live/kernel.py | import + open_market | Gateway / motor enter |
| Helix Sovereign | helix_sovereign_pro.py | python3 helix_sovereign_pro.py | Skor≥eşik ENTER TRY |
| Alpha Core | alpha_core.py | python3 alpha_core.py | Alpha sinyal |
| Atlas Quantum | ATLAS_QUANTUM_CORE.py | python3 ATLAS_QUANTUM_CORE.py | Quantum skor |
| Aggressive Live | aggressive_live_engine.py | python3 aggressive_live_engine.py | Momentum |
| Aggressive Futures | aggressive_futures_bot.py | python3 aggressive_futures_bot.py | Futures bot |
| Aggressive Short | aggressive_short_hunter.py | python3 aggressive_short_hunter.py | Short hunter |
| Adaptive Profit | adaptive_profit_runtime.py | python3 adaptive_profit_runtime.py | Profit runtime |
| FINAL LIVE HOTFIX | FINAL_LIVE_HOTFIX.py | python3 FINAL_LIVE_HOTFIX.py | Hotfix path |
| Helix TS | HelixSovereignEngine.ts | npx ts-node HelixSovereignEngine.ts | TS helix |
| CatE USDT | BinanceFuturesEngineCatE.ts | ts-node BinanceFuturesEngineCatE.ts | CatE |
| CatE USDC | CatEofUsdcFuturesEngine.ts | ts-node CatEofUsdcFuturesEngine.ts | USDC |
| Config gate | config.py | validate_startup() | Process start |
| ModeGuard | core/mode_guard.py | assert_live_safe() | LIVE DENY gates |
| PortfolioRisk | core/portfolio_risk.py | evaluate/require | Capital/leverage |
| Gateway | core/execution_gateway.py | submit(OrderIntent) | Idempotent send |

## Destek / kontrol
| Bileşen | Port/Path | Rol |
|---|---|---|
| control_plane | 127.0.0.1:8787 | Registry / health |
| UI gateway | 8788 | Panel |
| Bridge | 8100 | Parliament bridge |

## Yasak
Paper, mock, simulation, testnet endpoint, AUTO_PAPER=1 under LIVE.
