import unittest

from live.kernel import LiveKernel


class FakeLiveKernel(LiveKernel):
    def __init__(self, order_states, trades):
        self.order_states = list(order_states)
        self.trades = trades
        self.calls = []
        super().__init__(env={"BINANCE_API_KEY": "test-key", "BINANCE_API_SECRET": "test-secret"})

    def sync_time(self):
        return None

    def _http(self, method, path, params=None, signed=False, weight=1, is_order=False, retries=3):
        params = params or {}
        self.calls.append((method, path, dict(params), is_order))
        if path == self.v["order"] and method == "GET":
            if not self.order_states:
                raise AssertionError("unexpected order-state read")
            return self.order_states.pop(0)
        if path == self.v["order"] and method == "DELETE":
            return {"status": "CANCELED"}
        if path == self.v["userTrades"] and method == "GET":
            return self.trades
        raise AssertionError("unexpected API call %s %s" % (method, path))


class LiveFillContractTests(unittest.TestCase):
    def test_reconciles_actual_exchange_trades(self):
        kernel = FakeLiveKernel(
            [{"status": "FILLED", "executedQty": "0.02"}],
            [
                {"orderId": 10, "price": "100", "qty": "0.01", "commission": "0.01", "realizedPnl": "0"},
                {"orderId": 10, "price": "102", "qty": "0.01", "commission": "0.01", "realizedPnl": "0"},
                {"orderId": 11, "price": "999", "qty": "1", "commission": "0", "realizedPnl": "0"},
            ],
        )
        fill = kernel.resolve_fill("BTCUSDT", 10, 77, 0.02)
        self.assertEqual(fill["source"], "userTrades")
        self.assertEqual(fill["qty"], 0.02)
        self.assertEqual(fill["avg"], 101)
        self.assertEqual(fill["commission"], 0.02)

    def test_cancels_partial_remainder_and_reconciles_executed_quantity(self):
        kernel = FakeLiveKernel(
            [
                {"status": "PARTIALLY_FILLED", "executedQty": "0.01"},
                {"status": "CANCELED", "executedQty": "0.01"},
            ],
            [{"orderId": 12, "price": "100", "qty": "0.01", "commission": "0.01", "realizedPnl": "0"}],
        )
        fill = kernel.resolve_fill("BTCUSDT", 12, 100, 0.02)
        self.assertEqual(fill["qty"], 0.01)
        self.assertEqual(fill["status"], "CANCELED")
        self.assertTrue(any(call[0] == "DELETE" for call in kernel.calls))

    def test_never_creates_fill_from_order_ack_fallback(self):
        kernel = FakeLiveKernel(
            [{"status": "CANCELED", "executedQty": "0"}],
            [],
        )
        with self.assertRaisesRegex(RuntimeError, "no exchange-confirmed executed quantity"):
            kernel.resolve_fill("BTCUSDT", 13, 100, 0.02)

    def test_rejects_trade_ledger_quantity_mismatch(self):
        kernel = FakeLiveKernel(
            [{"status": "FILLED", "executedQty": "0.02"}],
            [{"orderId": 14, "price": "100", "qty": "0.01", "commission": "0.01", "realizedPnl": "0"}],
        )
        with self.assertRaisesRegex(RuntimeError, "could not be reconciled"):
            kernel.resolve_fill("BTCUSDT", 14, 100, 0.02)

    def test_requires_exchange_order_id(self):
        kernel = FakeLiveKernel([], [])
        with self.assertRaisesRegex(RuntimeError, "requires the exchange orderId"):
            kernel.resolve_fill("BTCUSDT", None, 100, 0.02)


if __name__ == "__main__":
    unittest.main()
