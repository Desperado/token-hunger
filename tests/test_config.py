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


def _endpoint_config(tmp_path, url, *, allow_private=False):
    allow = "\n    allow_private_endpoint: true" if allow_private else ""
    return write_config(
        tmp_path,
        f"""
targets:
  - type: endpoint
    id: service
    url: "{url}"{allow}
    cost:
      basis: per_request
      per_request: 0.01
cases:
  - input: hello
    expect: hello
""",
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",          # non-http scheme
        "file:///etc/passwd",           # file scheme
        "http://localhost:8080/run",    # loopback hostname
        "http://127.0.0.1/run",         # loopback IP
        "http://169.254.169.254/latest/meta-data",  # cloud metadata SSRF
        "http://10.0.0.5/internal",     # private range
        "http://192.168.1.10/x",        # private range
    ],
)
def test_endpoint_rejects_dangerous_url(tmp_path, url):
    with pytest.raises(ValueError):
        load_config(_endpoint_config(tmp_path, url))


def test_endpoint_allows_public_url(tmp_path):
    config = load_config(_endpoint_config(tmp_path, "https://api.example.com/run"))
    assert config.targets[0].raw["url"] == "https://api.example.com/run"


def test_endpoint_allows_local_url_with_opt_in(tmp_path):
    config = load_config(
        _endpoint_config(tmp_path, "http://localhost:11434/api", allow_private=True)
    )
    assert config.targets[0].raw["url"] == "http://localhost:11434/api"


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


@pytest.mark.parametrize("pool_size", [0, 11, 1.5, "true"])
def test_e2b_target_rejects_invalid_pool_size(tmp_path, pool_size):
    path = write_config(
        tmp_path,
        f"""
targets:
  - type: command
    id: sandboxed
    command: ["cat"]
    sandbox: e2b
    sandbox_pool_size: {pool_size}
    cost:
      basis: per_second
      per_second: 0.001
cases:
  - input: hello
    expect: hello
""",
    )

    with pytest.raises(ValueError, match="sandbox_pool_size"):
        load_config(path)


def test_e2b_target_accepts_ten_sandbox_pool(tmp_path):
    path = write_config(
        tmp_path,
        """
targets:
  - type: command
    id: sandboxed
    command: ["cat"]
    sandbox: e2b
    sandbox_pool_size: 10
    cost:
      basis: per_second
      per_second: 0.001
cases:
  - input: hello
    expect: hello
""",
    )

    config = load_config(path)

    assert config.targets[0].raw["sandbox_pool_size"] == 10


@pytest.mark.parametrize("timeout", [0, -5, 3601, 1.5, "true"])
def test_e2b_target_rejects_invalid_timeout(tmp_path, timeout):
    path = write_config(
        tmp_path,
        f"""
targets:
  - type: command
    id: sandboxed
    command: ["cat"]
    sandbox: e2b
    timeout: {timeout}
    cost:
      basis: per_second
      per_second: 0.001
cases:
  - input: hello
    expect: hello
""",
    )

    with pytest.raises(ValueError, match="sandbox timeout"):
        load_config(path)


def _e2b_code_check_config(tmp_path, *, allow=False, per_case=False):
    grader = tmp_path / "grade.py"
    grader.write_text("def grade(out, expect):\n    return True\n", encoding="utf-8")
    check_block = "" if per_case else "check:\n  type: code\n  function: grade.py:grade\n"
    case_check = (
        "    check:\n      type: code\n      function: grade.py:grade\n"
        if per_case
        else ""
    )
    allow_line = "allow_local_code_checks: true\n" if allow else ""
    return write_config(
        tmp_path,
        f"""
{allow_line}{check_block}targets:
  - type: command
    id: sandboxed
    command: ["cat"]
    sandbox: e2b
    cost:
      basis: per_second
      per_second: 0.001
cases:
  - input: hello
    expect: hello
{case_check}""",
    )


@pytest.mark.parametrize("per_case", [False, True])
def test_e2b_rejects_local_code_check(tmp_path, per_case):
    path = _e2b_code_check_config(tmp_path, per_case=per_case)
    with pytest.raises(ValueError, match="bypasses the e2b sandbox"):
        load_config(path)


def test_e2b_allows_code_check_with_explicit_opt_in(tmp_path):
    path = _e2b_code_check_config(tmp_path, allow=True)
    config = load_config(path)
    assert config.targets[0].raw["sandbox"] == "e2b"


def test_local_command_still_allows_code_check(tmp_path):
    grader = tmp_path / "grade.py"
    grader.write_text("def grade(out, expect):\n    return True\n", encoding="utf-8")
    path = write_config(
        tmp_path,
        """
check:
  type: code
  function: grade.py:grade
targets:
  - type: command
    id: local
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
    assert config.check["type"] == "code"
