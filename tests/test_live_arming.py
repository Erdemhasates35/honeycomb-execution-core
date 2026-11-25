import threading
import time
import unittest

from live.kernel import LiveKernel, TokenBucket


class NoNetworkKernel(LiveKernel):
    def sync_time(self):
        return None


class ProtectiveKernel(NoNetworkKernel):
    def __init__(self, fail_kind=None):
        self.fail_kind = fail_kind
        self.next_order_id = 100
        super().__init__(
            env={
                "BINANCE_API_KEY": "unit-test-key",
                "BINANCE_API_SECRET": "unit-test-secret",
                "LIVE_ARMED": "1",
            }
        )

    def _http(self, method, path, params=None, signed=False, weight=1, is_order=False, retries=3):
        if method == "POST" and path == self.v["order"]:
            if params and params.get("type") == self.fail_kind:
                raise RuntimeError("exchange rejected protective order")
            self.next_order_id += 1
            return {"orderId": self.next_order_id, "status": "NEW"}
        raise AssertionError("unexpected exchange call: %s %s" % (method, path))


class LockStub:
    def acquire(self, timeout=8.0):
        return True

    def release(self):
        return None


class OpenKernel(NoNetworkKernel):
    def __init__(self, close_fails=False):
        self.close_fails = close_fails
        self.close_called = False
        super().__init__(
            env={
                "BINANCE_API_KEY": "unit-test-key",
                "BINANCE_API_SECRET": "unit-test-secret",
                "LIVE_ARMED": "1",
            }
        )
        self.flock = LockStub()

    def balance_usdt(self):
        return 1000.0

    def book(self, symbol):
        return 100.0, 101.0, 100.5

    def set_margin(self, symbol, isolated=True):
        return None

    def set_leverage(self, symbol, lev):
        return None

    def place_market(self, symbol, side, qty, position_side=None, reduce_only=False):
        return {"orderId": 77, "avgPrice": "101"}

    def resolve_fill(self, symbol, order_id, fallback_avg=None, qty=None):
        return {"avg": 101.0, "qty": qty, "commission": 0.0, "rp": 0.0}

    def place_protect(self, symbol, side, entry, tp, sl, position_side=None):
        raise RuntimeError("protective stop rejected")

    def close_market(self, symbol, side, qty, position_side=None):
        self.close_called = True
        if self.close_fails:
            raise RuntimeError("emergency close could not be confirmed")
        return {"avg": 101.0, "qty": qty}


class LiveKernelSafetyTests(unittest.TestCase):
    def test_every_state_change_requires_live_arming_before_network(self):
        kernel = NoNetworkKernel(
            env={
                "BINANCE_API_KEY": "unit-test-key",
                "BINANCE_API_SECRET": "unit-test-secret",
                "LIVE_ARMED": "0",
            }
        )
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                with self.assertRaisesRegex(RuntimeError, "LIVE_ARMED=1"):
                    kernel._http(
                        method,
                        kernel.v["order"],
                        {"symbol": "BTCUSDT"},
                        signed=True,
                        is_order=True,
                    )

    def test_state_changes_must_be_signed_even_when_armed(self):
        kernel = NoNetworkKernel(
            env={
                "BINANCE_API_KEY": "unit-test-key",
                "BINANCE_API_SECRET": "unit-test-secret",
                "LIVE_ARMED": "1",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "must be signed"):
            kernel._http("POST", kernel.v["order"], {}, signed=False)

    def test_read_only_method_is_not_blocked_by_live_arm_gate(self):
        kernel = NoNetworkKernel(
            env={
                "BINANCE_API_KEY": "unit-test-key",
                "BINANCE_API_SECRET": "unit-test-secret",
                "LIVE_ARMED": "0",
            }
        )
        self.assertIsNone(kernel._assert_mutation_authorized("GET", signed=False))

    def test_token_bucket_refills_without_recursive_lock_deadlock(self):
        bucket = TokenBucket(wpm=600.0, o10=10.0)
        bucket.w = 0.0
        bucket.t = time.monotonic()
        finished = threading.Event()
        failures = []

        def consume():
            try:
                bucket.take(weight=1)
            except Exception as error:
                failures.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=consume, daemon=True)
        worker.start()
        self.assertTrue(finished.wait(0.5), "TokenBucket.take deadlocked while waiting for capacity")
        self.assertEqual(failures, [])

    def test_token_bucket_rejects_weight_above_capacity(self):
        bucket = TokenBucket(wpm=10.0, o10=10.0)
        with self.assertRaisesRegex(ValueError, "no greater than bucket capacity"):
            bucket.take(weight=11)

    def test_protective_order_rejection_is_not_silently_swallowed(self):
        kernel = ProtectiveKernel(fail_kind="STOP_MARKET")
        with self.assertRaisesRegex(RuntimeError, "exchange rejected protective order"):
            kernel.place_protect("BTCUSDT", "LONG", 100.0, 110.0, 90.0)
        
    def test_successful_protection_requires_both_exchange_order_ids(self):
        kernel = ProtectiveKernel()
        result = kernel.place_protect("BTCUSDT", "LONG", 100.0, 110.0, 90.0)
        self.assertEqual(len(result), 2)
        self.assertEqual({item["type"] for item in result}, {"TAKE_PROFIT_MARKET", "STOP_MARKET"})
        self.assertTrue(all(item["orderId"] for item in result))

    def test_open_market_attempts_emergency_flatten_if_protection_fails(self):
        kernel = OpenKernel()
        with self.assertRaisesRegex(RuntimeError, "emergency flatten completed"):
            kernel.open_market("BTCUSDT", "LONG", 0.01, 5, 1.0, 0.5, max_notional=200.0)
        self.assertTrue(kernel.close_called)

    def test_unconfirmed_emergency_flatten_is_raised_as_critical(self):
        kernel = OpenKernel(close_fails=True)
        with self.assertRaisesRegex(RuntimeError, "CRITICAL"):
            kernel.open_market("BTCUSDT", "LONG", 0.01, 5, 1.0, 0.5, max_notional=200.0)
        self.assertTrue(kernel.close_called)


if __name__ == "__main__":
    unittest.main()
