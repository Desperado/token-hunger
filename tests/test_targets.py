import sys
from types import SimpleNamespace

import pytest

from costbench.config import InfraCost, TargetSpec, TaskSpec
from costbench.pricing import AmortizedGpuPrice, PricingTable
from costbench.targets import ModelTarget


def _response(text="ok", input_tokens=100, output_tokens=100):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        ),
    )


def test_model_target_uses_separate_execution_model(monkeypatch):
    calls = []
    fake_litellm = SimpleNamespace(
        completion=lambda **kwargs: calls.append(kwargs) or _response()
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    spec = TargetSpec(
        type="model",
        id="local/gemma-27b",
        raw={
            "type": "model",
            "id": "local/gemma-27b",
            "model": "ollama/gemma3:27b",
        },
    )
    pricing = PricingTable(
        {
            "local/gemma-27b": AmortizedGpuPrice(
                gpu_hourly_rate=1.0,
                throughput_tokens_per_sec=100,
            )
        }
    )

    ModelTarget(spec, pricing).run(TaskSpec(), "hello")

    assert calls[0]["model"] == "ollama/gemma3:27b"


def test_model_target_applies_infra_override_and_gpu_basis(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(completion=lambda **kwargs: _response()),
    )
    spec = TargetSpec(
        type="model",
        id="local/gemma-27b",
        raw={"type": "model", "id": "local/gemma-27b"},
        infra_cost=InfraCost(
            gpu_hourly_rate=3.6,
            throughput_tokens_per_sec=100,
        ),
    )
    pricing = PricingTable(
        {
            "local/gemma-27b": AmortizedGpuPrice(
                gpu_hourly_rate=1.0,
                throughput_tokens_per_sec=1000,
            )
        }
    )

    output = ModelTarget(spec, pricing).run(TaskSpec(), "hello")

    assert output.cost == pytest.approx(0.002)
    assert output.cost_basis == "amortized GPU (batch 1)"
