import pytest

from costbench.cli import _apply_pull_params


def test_apply_pull_params_parses_typed_values():
    config = {"source": {"type": "sql", "params": {"project_id": 1}}}

    _apply_pull_params(config, ["project_id=220", "active=true", "label=demo"])

    assert config["source"]["params"] == {
        "project_id": 220,
        "active": True,
        "label": "demo",
    }


def test_apply_pull_params_rejects_invalid_shape():
    with pytest.raises(ValueError, match="key=value"):
        _apply_pull_params({"source": {"type": "sql"}}, ["project_id"])
