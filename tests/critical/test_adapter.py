# tests/critical/test_adapter.py
from python_engine.exchange.adapter import round_to_step, round_price, normalize_quantity


def test_rounding():
    assert round_to_step(1.2345, 0.01) == 1.23
    assert round_price(100.1234, 0.1) == 100.1
    assert normalize_quantity(0.001, 0.001, 0.001) == 0.001
