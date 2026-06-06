from costbench.checks import make_check
from costbench.ui_examples import presets
import json


def test_examples_have_two_levels_and_unique_ids():
    examples = presets()
    ids = [example["id"] for example in examples]

    assert len(ids) == len(set(ids))
    assert {example["level"] for example in examples} == {1, 2, 3}
    assert len([example for example in examples if example["level"] == 2]) == 5
    assert len([example for example in examples if example["level"] == 3]) == 4


def test_advanced_examples_are_substantial_and_deterministically_gradable():
    for example in presets():
        if example["level"] < 2:
            continue

        assert len(example["cases"]) >= 10
        check = make_check(example["task"]["check"])
        for case in example["cases"]:
            # Every authored ground truth must pass its own deterministic grader.
            assert check(str(case["expect"]), case["expect"]).passed


def test_advanced_examples_cover_multiple_answer_outcomes():
    for example in presets():
        if example["level"] >= 2:
            assert len({str(case["expect"]) for case in example["cases"]}) >= 4


def test_level_three_examples_record_opus_authoring_provenance():
    level_three = [example for example in presets() if example["level"] == 3]

    assert level_three
    assert all(
        example["authoring"]["model"] == "anthropic/claude-opus-4-6"
        and example["authoring"]["reviewed"] is True
        and example["authoring"]["promptTokens"] > 0
        and example["authoring"]["outputTokens"] > 0
        and example["authoring"]["validation"]["cases"] == 12
        and example["authoring"]["validation"]["passes"] >= 11
        for example in level_three
    )


def test_qualitymax_dump_becomes_ui_preset(tmp_path):
    config_dir = tmp_path / "examples" / "qualitymax"
    dump_dir = tmp_path / ".context"
    config_dir.mkdir(parents=True)
    dump_dir.mkdir()
    (dump_dir / "qualitymax_crawls.jsonl").write_text(
        json.dumps({"input": "URL: https://example.com", "expect": "completed"})
        + "\n",
        encoding="utf-8",
    )
    (config_dir / "crawl.label.yaml").write_text(
        """
name: QualityMax crawls
targets:
  - type: model
    id: anthropic/claude-haiku-4-5
task:
  system: Predict completed or failed.
  prompt_template: "{input}"
check: exact
cases:
  source: file
  path: ../../.context/qualitymax_crawls.jsonl
""",
        encoding="utf-8",
    )

    qualitymax = next(
        example
        for example in presets(base_dir=tmp_path)
        if example["id"] == "qualitymax-crawls"
    )

    assert qualitymax["cases"][0]["expect"] == "completed"
    assert len(qualitymax["configFingerprint"]) == 12
