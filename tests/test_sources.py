import json

import pytest

from costbench.config import load_config
from costbench.sources import load_cases


def _write(path, body):
    path.write_text(body, encoding="utf-8")
    return path


def test_inline_list_backcompat(tmp_path):
    cases, key = load_cases(
        [{"input": "hi", "expect": "yo"}, {"input": "a", "expect": "b"}],
        base_dir=tmp_path,
    )
    assert key == ""
    assert [c.input for c in cases] == ["hi", "a"]
    assert cases[0].expect == "yo"


def test_inline_source_form(tmp_path):
    cases, key = load_cases(
        {"source": "inline", "items": [{"input": "x", "expect": "y"}]},
        base_dir=tmp_path,
    )
    assert key == ""
    assert cases[0].expect == "y"


def test_file_jsonl_with_field_mapping(tmp_path):
    dump = tmp_path / "cases.jsonl"
    dump.write_text(
        json.dumps({"title": "Login", "steps": "click", "result_status": "passed"})
        + "\n"
        + json.dumps({"title": "Logout", "steps": "tap", "result_status": "failed"})
        + "\n",
        encoding="utf-8",
    )
    cases, key = load_cases(
        {
            "source": "file",
            "path": str(dump),
            "input_template": "{title}: {steps}",
            "expect_field": "result_status",
        },
        base_dir=tmp_path,
    )
    assert key  # a content key is produced for fingerprinting
    assert cases[0].input == "Login: click"
    assert cases[0].expect == "passed"
    assert cases[1].expect == "failed"


def test_file_drop_unlabeled(tmp_path):
    dump = tmp_path / "cases.jsonl"
    dump.write_text(
        json.dumps({"input": "a", "expect": "passed"}) + "\n"
        + json.dumps({"input": "b", "expect": None}) + "\n"
        + json.dumps({"input": "c", "expect": ""}) + "\n",
        encoding="utf-8",
    )
    cases, _ = load_cases(
        {"source": "file", "path": str(dump), "drop_unlabeled": True},
        base_dir=tmp_path,
    )
    assert [c.input for c in cases] == ["a"]


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown case source"):
        load_cases({"source": "sql", "query": "..."}, base_dir=tmp_path)


def test_missing_input_field_errors(tmp_path):
    dump = tmp_path / "cases.jsonl"
    dump.write_text(json.dumps({"expect": "passed"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'input'"):
        load_cases({"source": "file", "path": str(dump)}, base_dir=tmp_path)


def test_config_fingerprint_folds_file_content(tmp_path):
    dump = tmp_path / "cases.jsonl"
    cfg = tmp_path / "bench.yaml"
    _write(
        cfg,
        """
name: t
targets:
  - type: command
    id: cat
    command: ["cat"]
cases:
  source: file
  path: cases.jsonl
""",
    )
    dump.write_text(json.dumps({"input": "a", "expect": "a"}) + "\n", encoding="utf-8")
    fp1 = load_config(cfg).fingerprint

    # Same config text, different dump content → different fingerprint.
    dump.write_text(json.dumps({"input": "b", "expect": "b"}) + "\n", encoding="utf-8")
    fp2 = load_config(cfg).fingerprint

    assert fp1 != fp2
    assert len(fp1) == 12


def test_config_inline_still_loads(tmp_path):
    cfg = tmp_path / "bench.yaml"
    _write(
        cfg,
        """
targets:
  - type: command
    id: cat
    command: ["cat"]
cases:
  - input: hello
    expect: hello
""",
    )
    config = load_config(cfg)
    assert len(config.cases) == 1
    assert config.cases[0].expect == "hello"
