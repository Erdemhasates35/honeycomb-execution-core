# tests/critical/test_idempotency.py
from python_engine.idempotency import IdempotencySQLite


def test_idempotency_put_get(tmp_path):
    db = tmp_path / "idemp.db"
    s = IdempotencySQLite(str(db))
    cid = 'cli-1'
    res = {'orderId': 123}
    s.put(cid, res)
    got = s.get(cid)
    assert got == res
