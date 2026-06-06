import json

from costbench.calibration import import_calibration
from costbench.history import load_observations


def test_import_calibration_maps_filters_and_deduplicates(tmp_path):
    benchmark = tmp_path / "benchmark.yaml"
    benchmark.write_text(
        """
name: crawl
targets:
  - type: model
    id: anthropic/claude-haiku-4-5
  - type: model
    id: openai/gpt-5-mini
cases:
  - input: crawl one
    expect: completed
""",
        encoding="utf-8",
    )
    source = tmp_path / "costs.jsonl"
    rows = [
        {
            "id": "one",
            "service": "crawl",
            "model": "claude-haiku-4-5",
            "input_tokens": 100,
            "output_tokens": 20,
            "cost_usd": "0.001",
            "created_at": "2026-06-06T00:00:00Z",
        },
        {
            "id": "two",
            "service": "crawl",
            "model": "unknown-model",
            "input_tokens": 100,
            "output_tokens": 20,
            "cost_usd": 0.001,
        },
        {
            "id": "three",
            "service": "vtp",
            "model": "claude-haiku-4-5",
            "input_tokens": 100,
            "output_tokens": 20,
            "cost_usd": 0.001,
        },
        {
            "id": "four",
            "service": "crawl",
            "model": "gpt-5-mini",
            "input_tokens": "not-a-number",
            "output_tokens": 20,
            "cost_usd": 0.001,
        },
    ]
    source.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    config = tmp_path / "calibrate.yaml"
    config.write_text(
        """
benchmark: benchmark.yaml
source: costs.jsonl
source_label: qualitymax
filters:
  service: crawl
target_map:
  claude-haiku-4-5: anthropic/claude-haiku-4-5
  gpt-5-mini: openai/gpt-5-mini
""",
        encoding="utf-8",
    )
    history = tmp_path / "history.jsonl"

    first = import_calibration(
        config,
        history_path=history,
        allowed_root=tmp_path,
    )
    second = import_calibration(
        config,
        history_path=history,
        allowed_root=tmp_path,
    )

    assert first.rows == 4
    assert first.matched == 3
    assert first.imported == 1
    assert first.duplicates == 0
    assert first.skipped == 3
    assert second.imported == 0
    assert second.duplicates == 1

    loaded = load_observations(history)
    assert len(loaded) == 1
    assert loaded[0].target_id == "anthropic/claude-haiku-4-5"
    assert loaded[0].model_id == "claude-haiku-4-5"
    assert loaded[0].input_tokens == 100
    assert loaded[0].cost == 0.001
    assert loaded[0].source == "qualitymax"
    assert loaded[0].observation_id.startswith("qualitymax:")


def test_import_calibration_rejects_path_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "benchmark.yaml").write_text(
        "targets: [{type: model, id: anthropic/claude-haiku-4-5}]\n"
        "cases: [{input: x, expect: y}]\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    config = root / "calibrate.yaml"
    config.write_text(
        """
benchmark: ../benchmark.yaml
source: ../outside.jsonl
""",
        encoding="utf-8",
    )

    try:
        import_calibration(config, allowed_root=root)
    except ValueError as exc:
        assert "escapes allowed root" in str(exc)
    else:
        raise AssertionError("path traversal was not rejected")


def test_import_calibration_rejects_symlink_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "benchmark.yaml").write_text(
        "targets: [{type: model, id: anthropic/claude-haiku-4-5}]\n"
        "cases: [{input: x, expect: y}]\n",
        encoding="utf-8",
    )
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    (root / "source.jsonl").symlink_to(outside)
    config = root / "calibrate.yaml"
    config.write_text(
        """
benchmark: benchmark.yaml
source: source.jsonl
""",
        encoding="utf-8",
    )

    try:
        import_calibration(config, allowed_root=root)
    except ValueError as exc:
        assert "escapes allowed root" in str(exc)
    else:
        raise AssertionError("symlink escape was not rejected")


def test_import_calibration_rejects_nested_case_source_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text(
        json.dumps({"input": "secret", "expect": "completed"}) + "\n",
        encoding="utf-8",
    )
    (root / "costs.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "benchmark.yaml").write_text(
        """
targets:
  - type: model
    id: anthropic/claude-haiku-4-5
cases:
  source: file
  path: ../outside.jsonl
""",
        encoding="utf-8",
    )
    config = root / "calibrate.yaml"
    config.write_text(
        """
benchmark: benchmark.yaml
source: costs.jsonl
""",
        encoding="utf-8",
    )

    try:
        import_calibration(config, allowed_root=root)
    except ValueError as exc:
        assert "file case source" in str(exc)
        assert "escapes allowed root" in str(exc)
    else:
        raise AssertionError("nested case-source traversal was not rejected")


def test_import_calibration_rejects_unsafe_yaml_tag(tmp_path):
    config = tmp_path / "calibrate.yaml"
    config.write_text(
        "!!python/object/apply:os.system ['echo unsafe']\n",
        encoding="utf-8",
    )

    try:
        import_calibration(config, allowed_root=tmp_path)
    except ValueError as exc:
        assert "invalid calibration YAML" in str(exc)
    else:
        raise AssertionError("unsafe YAML tag was not rejected")
