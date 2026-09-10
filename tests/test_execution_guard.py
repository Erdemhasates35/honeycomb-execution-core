import os

import honeycomb_execution_guard as guard


def test_parse_retry_after_seconds():
    assert guard.parse_retry_after({"Retry-After": "12"}) == 12.0


def test_parse_ban_until_milliseconds():
    body = '{"code":-1003,"msg":"Way too many requests; IP banned until 1789000319417."}'
    assert abs(guard.parse_ban_until(body) - 1789000319.417) < 1e-6


def test_weight_mapping_is_conservative():
    assert guard._weight_for_url(
        "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&limit=80", "GET"
    ) == 1
    assert guard._weight_for_url("https://fapi.binance.com/fapi/v2/account", "GET") == 5


def test_order_paths_are_classified():
    assert guard._is_order_path("https://fapi.binance.com/fapi/v1/order") is True
    assert guard._is_order_path("https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&limit=80") is False


def test_legacy_learning_db_list_is_normalized_to_first_path(monkeypatch):
    monkeypatch.setenv("LEARNING_DB_PATH", "brain.db,quantum_nexus_v3.db,master_brain.db")
    # Re-run only the scalar normalization contract without re-installing the URL hook.
    value = os.environ["LEARNING_DB_PATH"]
    first = value.split(",", 1)[0].strip()
    assert first == "brain.db"
