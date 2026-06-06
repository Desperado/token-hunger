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

    first = import_calibration(config, history_path=history)
    second = import_calibration(config, history_path=history)

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
