import json
from pathlib import Path

from orchestrator import control_plane


def test_read_registry_recovers_empty_file(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text("", encoding="utf-8")
    monkeypatch.setattr(control_plane, "REGISTRY", registry)
    value, recovered = control_plane._read_registry()
    assert recovered is True
    assert value["engines"] == []
    assert value["modes"] == ["TESTNET", "PAPER", "LIVE"]


def test_read_registry_recovers_malformed_json(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(control_plane, "REGISTRY", registry)
    value, recovered = control_plane._read_registry()
    assert recovered is True
    assert value["project"] == control_plane.ROOT.name


def test_write_registry_is_valid_json(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    monkeypatch.setattr(control_plane, "REGISTRY", registry)
    control_plane._write_registry({"project": "test", "engines": [{"path": "engine.py"}]})
    loaded = json.loads(registry.read_text(encoding="utf-8"))
    assert loaded["engines"][0]["path"] == "engine.py"
    assert not registry.with_suffix(".json.tmp").exists()


def test_inventory_repairs_malformed_registry(tmp_path, monkeypatch):
    root = tmp_path
    registry = root / "registry.json"
    runtime = root / "runtime"
    runtime.mkdir()
    registry.write_text("not-json", encoding="utf-8")
    source = root / "nexus_engine.py"
    source.write_text("def engine():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(control_plane, "ROOT", root)
    monkeypatch.setattr(control_plane, "REGISTRY", registry)
    data = control_plane.inventory()
    assert data["registry_recovered"] is True
    assert json.loads(registry.read_text(encoding="utf-8"))["engines"]


def test_current_status_degrades_quality_failure(monkeypatch):
    monkeypatch.setattr(control_plane, "inventory", lambda: {"engines": [], "files": [], "registry_recovered": False})
    monkeypatch.setattr(control_plane, "quality_report", lambda: (_ for _ in ()).throw(RuntimeError("quality unavailable")))
    status = control_plane.current_status()
    assert status["telemetry"]["quality"]["ok"] is False
    assert status["quality"]["summary"]["core_9plus"] is False
