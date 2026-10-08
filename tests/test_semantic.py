"""The inactive semantic feature must never manufacture security findings."""

from code_compass.analysis.orchestrator import analyze
from code_compass.discovery import discover


def test_semantic_flag_does_not_invent_findings(tmp_path):
    (tmp_path / "insecure.py").write_text("def digest(value):\n    return value\n", encoding="utf-8")
    result = analyze(discover(tmp_path), semantic=True)
    assert result.semantic_findings == []
    assert result.repo_stats["semantic_status"] == "unavailable"


def test_semantic_off_is_labeled_disabled(tmp_path):
    (tmp_path / "safe.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    result = analyze(discover(tmp_path), semantic=False)
    assert result.semantic_findings == []
    assert result.repo_stats["semantic_status"] == "disabled"
