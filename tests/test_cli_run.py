from costbench.cli import _apply_case_limit
from costbench.config import Case, Config, TaskSpec


def _config():
    return Config(
        name="test",
        targets=[],
        task=TaskSpec(),
        check="exact",
        cases=[Case("one", "1"), Case("two", "2"), Case("three", "3")],
        fingerprint="full-config",
    )


def test_case_limit_gets_distinct_deterministic_fingerprint():
    first = _config()
    second = _config()

    _apply_case_limit(first, 1)
    _apply_case_limit(second, 1)

    assert len(first.cases) == 1
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != "full-config"


def test_non_truncating_case_limit_keeps_original_fingerprint():
    config = _config()

    _apply_case_limit(config, 3)

    assert config.fingerprint == "full-config"
