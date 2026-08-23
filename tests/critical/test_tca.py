# tests/critical/test_tca.py
from python_engine.tca.tca import TCA


def test_tca_record_predict():
    t = TCA()
    t.record(10, 0.001, 0.002)
    p = t.predict(10)
    assert isinstance(p, float)
