import json
import sys
from types import SimpleNamespace

import pytest

from costbench.analyze import analyze_config
from costbench.config import Case, Config, TaskSpec
from costbench.pricing import ModelPrice, PricingTable


def _config():
    return Config(
        name="triage",
        targets=[],
        task=TaskSpec(
            system="Classify support tickets.",
            prompt_template="Ticket: {input}",
        ),
        check="exact",
        cases=[
            Case("account locked", "SECRET_EXPECTED_VALUE"),
            Case("invoice missing", "RESOLVE"),
        ],
    )


def _response(payload, input_tokens=100, output_tokens=20):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload))
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        ),
    )


def test_analyze_config_uses_bounded_inputs_and_excludes_answers(monkeypatch):
    calls = []
    payload = {
        "task_type": "general",
        "category": "classification",
        "complexity": "low",
        "confidence": 0.92,
        "reason": "Short constrained labels.",
        "signals": ["binary output", "short inputs"],
    }
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            completion=lambda **kwargs: calls.append(kwargs) or _response(payload)
        ),
    )

    pricing = PricingTable(
        {"qwen/qwen3.5-flash": ModelPrice(0.10, 0.40)}
    )
    analysis = analyze_config(
        _config(),
        "qwen/qwen3.5-flash",
        pricing=pricing,
    )

    sent = calls[0]["messages"][1]["content"]
    assert "account locked" in sent
    assert "SECRET_EXPECTED_VALUE" not in sent
    assert calls[0]["model"] == "qwen/qwen3.5-flash"
    assert analysis.task_type == "general"
    assert analysis.category == "classification"
    assert analysis.complexity == "low"
    assert analysis.cost == pytest.approx(0.000018)


def test_analyze_config_accepts_fenced_json(monkeypatch):
    content = """```json
{"task_type":"coding","category":"coding","complexity":"high",
"confidence":0.8,"reason":"Repository-level changes.","signals":["code"]}
```"""
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            completion=lambda **kwargs: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )
                ]
            )
        ),
    )

    analysis = analyze_config(_config(), "qwen/test")

    assert analysis.task_type == "coding"
    assert analysis.complexity == "high"


def test_analyze_config_rejects_invalid_taxonomy(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            completion=lambda **kwargs: _response(
                {
                    "task_type": "legal",
                    "category": "other",
                    "complexity": "medium",
                    "confidence": 0.5,
                    "reason": "Domain task.",
                    "signals": [],
                }
            )
        ),
    )

    with pytest.raises(ValueError, match="task_type"):
        analyze_config(_config(), "qwen/test")


def _content_response(content):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content))
        ]
    )


def test_analyze_config_extracts_json_from_prose(monkeypatch):
    content = (
        'Here is the classification: '
        '{"task_type":"math","category":"math","complexity":"medium",'
        '"confidence":0.7,"reason":"Arithmetic over {braced} inputs.",'
        '"signals":["numbers"]}\nLet me know if you need more.'
    )
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(completion=lambda **kwargs: _content_response(content)),
    )

    analysis = analyze_config(_config(), "qwen/test")

    assert analysis.task_type == "math"
    assert analysis.category == "math"
    assert analysis.reason == "Arithmetic over {braced} inputs."


def test_analyze_config_caps_signal_length(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            completion=lambda **kwargs: _response(
                {
                    "task_type": "general",
                    "category": "other",
                    "complexity": "low",
                    "confidence": 0.5,
                    "reason": "Generic.",
                    "signals": ["x" * 1000],
                }
            )
        ),
    )

    analysis = analyze_config(_config(), "qwen/test")

    assert len(analysis.signals[0]) == 200
