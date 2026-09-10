from orchestrator.ui_control_plane import UI_PROXY_ROUTES, normalize_mode, ui_capabilities


def test_normalize_mode_accepts_operational_modes():
    assert normalize_mode("testnet") == "TESTNET"
    assert normalize_mode("paper") == "PAPER"
    assert normalize_mode("shadow") == "SHADOW"
    assert normalize_mode("live") == "LIVE"
    assert normalize_mode("invalid") is None


def test_proxy_routes_are_read_only_except_mode():
    assert UI_PROXY_ROUTES["/api/ui/status"] == ("GET", "http://127.0.0.1:8787/api/status")
    assert UI_PROXY_ROUTES["/api/ui/overview"] == ("GET", "http://127.0.0.1:8100/summary")
    assert UI_PROXY_ROUTES["/api/ui/positions"] == ("GET", "http://127.0.0.1:8100/positions")
    assert "/api/ui/order" not in UI_PROXY_ROUTES


def test_capabilities_are_explicit_and_non_fabricating(monkeypatch):
    monkeypatch.setenv("CONTROL_PORT", "8787")
    caps = ui_capabilities()
    assert caps["mode"]["supported"] == ["TESTNET", "PAPER", "SHADOW", "LIVE"]
    assert caps["orders"]["browser_submission"] is False
    assert caps["data_policy"] == "REAL_BACKEND_ONLY"
