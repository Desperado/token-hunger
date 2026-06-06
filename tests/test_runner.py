import sys

import pytest

from costbench.config import Case, Config, CostSpec, TargetSpec, TaskSpec
from costbench.runner import run_benchmark


def command_target(target_id, output, cost):
    return TargetSpec(
        type="command",
        id=target_id,
        raw={
            "type": "command",
            "id": target_id,
            "command": [sys.executable, "-c", f"print({output!r})"],
        },
        cost=CostSpec(basis="per_request", per_request=cost),
    )


def config_with(targets):
    return Config(
        name="test",
        targets=targets,
        task=TaskSpec(),
        check="exact",
        cases=[Case("one", "PASS"), Case("two", "FAIL")],
        fingerprint="abc123",
    )


def test_ranks_by_cost_per_success_not_cost_per_run():
    cheap_inaccurate = command_target("cheap", "PASS", 0.001)
    premium_accurate = TargetSpec(
        type="command",
        id="premium",
        raw={
            "type": "command",
            "id": "premium",
            "command": [
                sys.executable,
                "-c",
                "import sys; print('PASS' if sys.stdin.read() == 'one' else 'FAIL')",
            ],
        },
        cost=CostSpec(basis="per_request", per_request=0.0015),
    )

    report = run_benchmark(config_with([cheap_inaccurate, premium_accurate]))

    assert report.results[0].cost_per_run == 0.001
    assert report.results[1].cost_per_run == 0.0015
    assert report.results[0].cost_per_success == pytest.approx(0.002)
    assert report.results[1].cost_per_success == pytest.approx(0.0015)
    assert report.ranked_by_cost_per_success()[0].target_id == "premium"


def test_rejects_zero_concurrency():
    with pytest.raises(ValueError, match="at least 1"):
        run_benchmark(config_with([command_target("local", "PASS", 0.0)]), concurrency=0)


def test_unknown_cost_remains_unknown():
    target = command_target("local", "PASS", 0.0)
    target.cost = CostSpec()

    report = run_benchmark(config_with([target]))

    assert report.results[0].total_cost is None
    assert report.results[0].cost_per_success is None


def test_failed_attempt_keeps_declared_cost():
    target = TargetSpec(
        type="command",
        id="broken",
        raw={
            "type": "command",
            "id": "broken",
            "command": [sys.executable, "-c", "raise SystemExit(1)"],
        },
        cost=CostSpec(basis="per_request", per_request=0.25),
    )

    report = run_benchmark(config_with([target]))

    assert report.results[0].errors == 2
    assert report.results[0].total_cost == 0.5
    assert report.results[0].cost_per_success == float("inf")
