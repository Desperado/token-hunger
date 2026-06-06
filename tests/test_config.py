from pathlib import Path

import pytest

from costbench.config import build_config, load_config


def test_build_config_from_dict(tmp_path):
    cfg = build_config(
        {
            "name": "inmem",
            "task": {"system": "s", "prompt_template": "{input}"},
            "check": "contains",
            "targets": [{"type": "model", "id": "anthropic/claude-haiku-4-5"}],
            "cases": [{"input": "a", "expect": "b"}],
        },
        base_dir=tmp_path,
    )
    assert cfg.name == "inmem"
    assert cfg.check == "contains"
    assert cfg.targets[0].id == "anthropic/claude-haiku-4-5"
    assert cfg.cases[0].expect == "b"
    assert len(cfg.fingerprint) == 12
    assert cfg.source_path is None


def test_build_config_fingerprint_is_stable_and_content_sensitive(tmp_path):
    base = {
        "task": {"system": "s"},
        "targets": [{"type": "model", "id": "openai/gpt-5"}],
        "cases": [{"input": "a", "expect": "b"}],
    }
    fp1 = build_config(dict(base), base_dir=tmp_path).fingerprint
    fp2 = build_config(dict(base), base_dir=tmp_path).fingerprint
    assert fp1 == fp2  # same input → same fingerprint
    changed = {**base, "cases": [{"input": "a", "expect": "DIFFERENT"}]}
    assert build_config(changed, base_dir=tmp_path).fingerprint != fp1


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
