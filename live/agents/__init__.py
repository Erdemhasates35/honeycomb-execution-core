# α-Agents Package — Production Only
# Agents 01-07 ready for honeycomb-execution-core + honeycomb_al
from .expectancy_gate import gate as expectancy_gate, update_trade, get_expectancy
from .correlation_kill import correlation_blocked, portfolio_heat
from .kelly_sizing import compute_size, kelly_fraction
from .ack_latency import latency_gate, record_ack
from .funding_capture import funding_signal, should_capture_funding
from .toxicity_filter import toxicity_score, toxicity_blocked
from .micro_arb import micro_arb_opportunity, execute_micro_arb_signal

__all__ = [
    "expectancy_gate", "update_trade", "get_expectancy",
    "correlation_blocked", "portfolio_heat",
    "compute_size", "kelly_fraction",
    "latency_gate", "record_ack",
    "funding_signal", "should_capture_funding",
    "toxicity_score", "toxicity_blocked",
    "micro_arb_opportunity", "execute_micro_arb_signal",
]
