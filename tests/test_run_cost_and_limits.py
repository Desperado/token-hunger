"""Cost-accounting and output-limit guarantees of the run/estimate payloads.

Two properties a cost benchmark must hold, pinned so neither regresses silently:

  1. run_payload reports costTotal — the actual total $ spent on each target.
     (cost_per_run is only an average over priced cases, so it can't recover the
     true total; costTotal can.)
  2. A request's outputTokens limit is enforced on the model call as
     params.max_tokens — not merely used to size the estimate — so the estimated
     cost and the executed run agree on the same output ceiling.

Model execution is stubbed so the run is offline and deterministic.
"""

from __future__ import annotations

import pytest

from costbench import server

MODEL = "anthropic/claude-haiku-4-5"  # vendor-prefixed id from models.yaml
TASK = {"system": None, "promptTemplate": "{input}", "check": "exact"}
CASES = [{"input": "ping", "expect": "ok"}, {"input": "ping2", "expect": "ok"}]


def test_run_payload_reports_total_cost(monkeypatch):
    def fake_run(self, task, case_input):
        from costbench.targets import CaseOutput

        return CaseOutput(
            text="ok", input_tokens=10, output_tokens=5,
            cost=0.10, cost_basis="test", latency=0.0,
        )

    monkeypatch.setattr("costbench.targets.ModelTarget.run", fake_run)
    result = server.run_payload({"task": TASK, "targets": [MODEL], "cases": CASES})

    row = result["rows"][0]
    assert "costTotal" in row
    assert row["costTotal"] == pytest.approx(0.20)  # 2 cases * 0.10, the true total


def test_output_token_limit_is_enforced_on_the_run(monkeypatch):
    captured = {}

    def fake_run(self, task, case_input):
        from costbench.targets import CaseOutput

        captured["max_tokens"] = self.params.get("max_tokens")
        return CaseOutput(text="ok", input_tokens=10, output_tokens=5,
                          cost=0.01, cost_basis="test", latency=0.0)

    monkeypatch.setattr("costbench.targets.ModelTarget.run", fake_run)
    server.run_payload(
        {"task": TASK, "targets": [MODEL], "cases": CASES, "outputTokens": 64}
    )
    assert captured["max_tokens"] == 64  # the requested cap reached the model call


def test_estimate_config_is_deterministic_under_an_output_limit():
    """With the same outputTokens, the estimate builds the same config each time,
    so the priced ceiling and the enforced run cap share one fingerprint."""
    body = {"task": TASK, "targets": [MODEL], "cases": CASES, "outputTokens": 128}
    fp1 = server.estimate_payload(body)["meta"]["configFingerprint"]
    fp2 = server.estimate_payload(body)["meta"]["configFingerprint"]
    assert fp1.startswith("cfg:")
    assert fp1 == fp2
