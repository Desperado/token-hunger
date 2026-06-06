from costbench.checks import make_check
from costbench.ui_examples import presets


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
