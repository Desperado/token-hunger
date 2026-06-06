import json

import pytest

from costbench.connectors import materialize, pull


def test_materialize_maps_and_passes_through(tmp_path):
    rows = [
        {"title": "Login", "steps": "click", "result_status": "passed",
         "expected_results": "user is logged in", "test_case_id": 1},
        {"title": "Logout", "steps": "tap", "result_status": "failed",
         "expected_results": "user is logged out", "test_case_id": 2},
    ]
    out = tmp_path / "dump.jsonl"
    result = materialize(
        rows,
        {
            "input_template": "{title}: {steps}",
            "expect": "{result_status}",
            "passthrough": ["expected_results", "test_case_id"],
        },
        out,
        source_label="sql",
    )
    assert result.written == 2
    assert result.dropped_unlabeled == 0
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert lines[0]["input"] == "Login: click"
    assert lines[0]["expect"] == "passed"
    assert lines[0]["expected_results"] == "user is logged in"
    assert lines[0]["test_case_id"] == 1

    meta = json.loads((tmp_path / "dump.jsonl.meta.json").read_text())
    assert meta["rows_written"] == 2
    assert meta["fingerprint"] == result.fingerprint


def test_materialize_fingerprint_is_deterministic(tmp_path):
    rows = [{"input": "a", "x": "passed"}]
    mapping = {"expect": "{x}"}
    r1 = materialize(rows, mapping, tmp_path / "a.jsonl", source_label="sql")
    r2 = materialize(rows, mapping, tmp_path / "b.jsonl", source_label="sql")
    assert r1.fingerprint == r2.fingerprint

    r3 = materialize([{"input": "z", "x": "passed"}], mapping, tmp_path / "c.jsonl",
                     source_label="sql")
    assert r3.fingerprint != r1.fingerprint


def test_materialize_drops_unlabeled(tmp_path):
    rows = [
        {"input": "a", "s": "passed"},
        {"input": "b", "s": None},
        {"input": "c", "s": ""},
    ]
    result = materialize(
        rows, {"expect": "{s}", "drop_unlabeled": True},
        tmp_path / "d.jsonl", source_label="sql",
    )
    # _render turns None/"" into empty → dropped.
    assert result.written == 1
    assert result.dropped_unlabeled == 2


def test_pull_with_injected_fetcher(tmp_path):
    pull_config = {
        "source": {"type": "sql", "dsn_env": "X", "query": "select 1"},
        "out": "out.jsonl",
        "map": {"input_field": "input", "expect_field": "v"},
    }
    fake_rows = [{"input": "hello", "v": "passed"}]
    result = pull(pull_config, base_dir=tmp_path, fetcher=lambda src: fake_rows)
    assert result.written == 1
    assert (tmp_path / "out.jsonl").exists()


def test_pull_requires_source_type(tmp_path):
    with pytest.raises(ValueError, match="'source' mapping with a 'type'"):
        pull({"out": "x.jsonl", "map": {}}, base_dir=tmp_path, fetcher=lambda s: [])


def test_pull_requires_out(tmp_path):
    with pytest.raises(ValueError, match="'out' path"):
        pull({"source": {"type": "sql"}, "map": {}}, base_dir=tmp_path,
             fetcher=lambda s: [])


def test_pull_unknown_source_type_without_fetcher(tmp_path):
    with pytest.raises(ValueError, match="unknown pull source type"):
        pull({"source": {"type": "http"}, "out": "o.jsonl"}, base_dir=tmp_path)
