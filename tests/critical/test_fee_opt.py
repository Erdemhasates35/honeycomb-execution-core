# tests/critical/test_fee_opt.py
from python_engine.fees.fee_optimizer import FeeOptimizer


def test_fee_choice():
    f = FeeOptimizer(maker_rebate=0.0002, taker_fee=0.0004)
    assert f.choose(0.0) in ('maker', 'taker')
