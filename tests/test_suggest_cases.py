import pytest

from costbench import suggest_cases as sc


def test_parse_plain_json_array():
    out = sc._parse_cases('[{"input": "Japan", "expect": "Tokyo"}]')
    assert out == [{"input": "Japan", "expect": "Tokyo"}]


def test_parse_strips_code_fence_and_prose():
    text = "Here you go:\n```json\n[{\"input\":\"2+2\",\"expect\":4}]\n```\nThanks!"
    out = sc._parse_cases(text)
    assert out == [{"input": "2+2", "expect": 4}]


def test_parse_skips_malformed_items():
    out = sc._parse_cases('[{"input":"a","expect":"b"}, {"nope":1}, "junk"]')
    assert out == [{"input": "a", "expect": "b"}]


def test_parse_raises_without_array():
    with pytest.raises(ValueError):
        sc._parse_cases("sorry, I can't do that")


def test_pick_model_prefers_present_key(monkeypatch):
    for env, _ in sc._SUGGEST_PREFERENCE:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("COSTBENCH_SUGGEST_MODEL", raising=False)
    assert sc.pick_model() is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert sc.pick_model() == "anthropic/claude-haiku-4-5"
    monkeypatch.setenv("COSTBENCH_SUGGEST_MODEL", "openai/gpt-4o-mini")
    assert sc.pick_model() == "openai/gpt-4o-mini"


def test_suggest_cases_without_key_errors(monkeypatch):
    for env, _ in sc._SUGGEST_PREFERENCE:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("COSTBENCH_SUGGEST_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="no provider API key"):
        sc.suggest_cases({"system": "s", "check": "exact"})
