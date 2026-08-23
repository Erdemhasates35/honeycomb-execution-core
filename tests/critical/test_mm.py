# tests/critical/test_mm.py
from python_engine.market_maker.mm import MarketMaker, InventoryController


def test_mm_quote():
    mm = MarketMaker(spread=0.2)
    ic = InventoryController(target_inventory=0.0)
    adj = ic.inventory_adjustment(0.1)
    q = mm.quote(100.0, adj)
    assert 'bid' in q and 'ask' in q
