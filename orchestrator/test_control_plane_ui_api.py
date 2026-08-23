import json

from orchestrator import control_plane


def test_ui_mode_round_trip_requires_live_arm(monkeypatch, tmp_path):
    monkeypatch.setattr(control_plane, "STATE", tmp_path / "state.json")
    monkeypatch.delenv("LIVE_ARMED", raising=False)
    assert control_plane.validate_ui_mode("TESTNET") == (True, None)
    assert control_plane.validate_ui_mode("PAPER") == (True, None)
    assert control_plane.validate_ui_mode("LIVE") == (False, "LIVE_ARMED=1 required")


def test_ui_mode_round_trip_allows_live_when_explicitly_armed(monkeypatch, tmp_path):
    monkeypatch.setattr(control_plane, "STATE", tmp_path / "state.json")
    monkeypatch.setenv("LIVE_ARMED", "1")
    assert control_plane.validate_ui_mode("LIVE") == (True, None)
    control_plane.write_mode("LIVE")
    assert json.loads((tmp_path / "state.json").read_text())["mode"] == "LIVE"


def test_ui_proxy_paths_are_allowlisted():
    assert control_plane.UI_PROXY_PATHS["/api/ui/overview"] == "/summary"
    assert control_plane.UI_PROXY_PATHS["/api/ui/positions"] == "/positions"
    assert control_plane.UI_PROXY_PATHS["/api/ui/journal"] == "/journal"
    assert "/api/ui/order" not in control_plane.UI_PROXY_PATHS
