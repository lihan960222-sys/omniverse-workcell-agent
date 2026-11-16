from workcell_agent.reports import write_report


def test_report_escapes_names_and_preserves_missing_coverage(tmp_path):
    result = {"coverage": {"status": "not_executed", "reason": "no BRep"},
              "findings": [{"name": "<script>alert(1)</script>", "status": "unknown"}]}
    paths = write_report(result, tmp_path)
    text = paths["html"].read_text(encoding="utf-8")
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "not_executed" in text
