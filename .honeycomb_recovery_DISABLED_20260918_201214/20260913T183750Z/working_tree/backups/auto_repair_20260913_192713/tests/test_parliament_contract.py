import importlib
import sys
import types


def test_scan_symbol_missing_allow_is_fail_closed(monkeypatch, capsys):
    fake_alpha = types.SimpleNamespace(
        DEFENSE_ENABLED=True,
        get_technical_decision=lambda symbol: {"side": "LONG", "confidence": 80},
    )
    fake_kernel = types.SimpleNamespace(LiveKernel=lambda *a, **k: object(), load_env=lambda: {}, CircuitBreaker=lambda: None)
    monkeypatch.setitem(sys.modules, "alpha_core", fake_alpha)
    monkeypatch.setitem(sys.modules, "live.kernel", fake_kernel)
    sys.modules.pop("sovereign_parliament_engine", None)
    mod = importlib.import_module("sovereign_parliament_engine")
    mod.scan_symbol("BTCUSDT")
    out = capsys.readouterr().out
    assert "allow=False" in out
    assert "side=LONG" in out
