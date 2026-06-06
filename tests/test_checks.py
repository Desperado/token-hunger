from costbench.checks import make_check


def test_code_check_path_resolves_relative_to_base_dir(tmp_path):
    (tmp_path / "grader.py").write_text(
        "def grade(output, expect):\n    return output == expect\n",
        encoding="utf-8",
    )
    # cwd is the repo root, not tmp_path, so this only resolves via base_dir.
    check = make_check({"type": "code", "function": "grader.py:grade"}, tmp_path)
    assert check("x", "x").passed
    assert not check("x", "y").passed


def test_exact_normalizes_case_and_whitespace():
    result = make_check("exact")("  EsCaLaTe\n", "ESCALATE")
    assert result.passed


def test_numeric_supports_relative_tolerance():
    check = make_check({"type": "numeric", "tolerance": 0.05, "relative": True})
    assert check("The answer is 104", 100).passed
    assert not check("The answer is 106", 100).passed


def test_regex_can_be_case_sensitive():
    check = make_check({"type": "regex", "case_sensitive": True})
    assert check("ESCALATE", r"^ESCALATE$").passed
    assert not check("escalate", r"^ESCALATE$").passed
