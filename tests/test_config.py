from pathlib import Path

import pytest

from costbench.config import load_config


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "benchmark.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_minimal_command_config(tmp_path):
    path = write_config(
        tmp_path,
        """
targets:
  - type: command
    id: echo
    command: ["cat"]
    cost:
      basis: per_request
      per_request: 0.01
cases:
  - input: hello
    expect: hello
""",
    )

    config = load_config(path)

    assert config.name == "benchmark"
    assert config.targets[0].cost.amortized_per_request() == 0.01
    assert len(config.fingerprint) == 12


@pytest.mark.parametrize(
    "cost",
    [
        "{basis: made-up}",
        "{basis: per_request}",
        "{basis: subscription, monthly: 10}",
        "{basis: subscription, monthly: -1, expected_monthly_volume: 10}",
        "{basis: per_second, per_second: 0.001}",
    ],
)
def test_rejects_invalid_cost_specs(tmp_path, cost):
    path = write_config(
        tmp_path,
        f"""
targets:
  - type: command
    id: echo
    command: ["cat"]
    cost: {cost}
cases:
  - input: hello
    expect: hello
""",
    )

    with pytest.raises(ValueError):
        load_config(path)


def test_endpoint_requires_url(tmp_path):
    path = write_config(
        tmp_path,
        """
targets:
  - type: endpoint
    id: service
cases:
  - input: hello
    expect: hello
""",
    )

    with pytest.raises(ValueError, match="missing 'url'"):
        load_config(path)


def test_e2b_target_requires_explicit_per_second_rate(tmp_path):
    path = write_config(
        tmp_path,
        """
targets:
  - type: command
    id: sandboxed
    command: ["cat"]
    sandbox: e2b
cases:
  - input: hello
    expect: hello
""",
    )

    with pytest.raises(ValueError, match="e2b command targets require"):
        load_config(path)


@pytest.mark.parametrize("interval", ["nope", -0.1, ".inf", ".nan"])
def test_e2b_target_rejects_invalid_creation_interval(tmp_path, interval):
    path = write_config(
        tmp_path,
        f"""
targets:
  - type: command
    id: sandboxed
    command: ["cat"]
    sandbox: e2b
    sandbox_create_interval: {interval}
    cost:
      basis: per_second
      per_second: 0.001
cases:
  - input: hello
    expect: hello
""",
    )

    with pytest.raises(ValueError, match="sandbox_create_interval"):
        load_config(path)
