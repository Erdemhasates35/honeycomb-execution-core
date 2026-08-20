import json
from pathlib import Path

from orchestrator.quality_gate import SCHEMA_VERSION, evaluate_repository


ROOT = Path(__file__).resolve().parents[1]


def test_core_runtime_components_reach_enterprise_gate():
    report = evaluate_repository(ROOT)
    required = {"orchestrator/control_plane.py", "nexus_testnet_bridge.py", "run_nexus_testnet.sh", "runtime/start_testnet.sh"}
    scores = {item["path"]: item["score"] for item in report["files"]}
    assert required.issubset(scores)
    assert all(scores[path] >= 9.0 for path in required)
    assert report["summary"]["core_9plus"] is True


def test_quality_report_is_machine_verifiable(tmp_path):
    report = evaluate_repository(ROOT)
    out = tmp_path / "quality.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    loaded = json.loads(out.read_text())
    assert loaded["schema_version"] == SCHEMA_VERSION
    assert loaded["summary"]["total"] >= 4
    assert 0.0 <= loaded["summary"]["repository_score"] <= 10.0
