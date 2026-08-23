# tests/critical/test_stat_arb.py
from python_engine.stat_arb.cointegration import PairStatArb


def test_stat_methods():
    p = PairStatArb()
    z = p.zscore([1,2,3,4,5])
    assert isinstance(z, float)
