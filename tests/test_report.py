import json

from costbench.report import to_html, to_json, to_markdown
from costbench.runner import BenchmarkReport, CaseResult, TargetResult


def result(target_id="<script>alert(1)</script>", cost=0.01, passed=True):
    return TargetResult(
        target_id=target_id,
        target_type="command",
        cases=[
            CaseResult(
                case_input="input",
                expect="ok",
                output="ok",
                passed=passed,
                detail="",
                cost=cost,
                cost_basis="per-request",
                latency=0.1,
            )
        ],
    )


def test_html_escapes_target_values():
    report = BenchmarkReport("demo", "abc123", [result()])
    html = to_html(report)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_json_represents_infinite_cost_explicitly():
    report = BenchmarkReport(
        "demo", "abc123", [result(passed=False)], pricing_fingerprint="price123"
    )
    payload = json.loads(to_json(report))

    assert payload["results"][0]["cost_per_success"] is None
    assert payload["results"][0]["cost_per_success_infinite"] is True
    assert payload["pricing_fingerprint"] == "price123"


def test_markdown_contains_reproduction_metadata():
    report = BenchmarkReport("demo", "abc123", [result(target_id="local")])
    markdown = to_markdown(report)

    assert "cost per success" in markdown.lower()
    assert "abc123" in markdown
    assert "Methodology" in markdown
