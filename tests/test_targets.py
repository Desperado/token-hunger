import sys
from types import SimpleNamespace

import pytest

from costbench.config import CostSpec, InfraCost, TargetSpec, TaskSpec
from costbench.pricing import AmortizedGpuPrice, PricingTable
from costbench.targets import (
    CommandTarget,
    E2BCommandTarget,
    ModelTarget,
    build_target,
)


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


# --- e2b sandbox command target -------------------------------------------


class _FakeSandbox:
    """Minimal stand-in for e2b.Sandbox (the real one uses .create()/.kill())."""

    last = None

    def __init__(self):
        self.files_written = {}
        self.killed = False
        _FakeSandbox.last = self

    @classmethod
    def create(cls, template=None):
        sbx = cls()
        sbx.template = template
        return sbx

    def kill(self):
        self.killed = True

    @property
    def files(self):
        sbx = self

        class _Files:
            def write(self, path, content):
                sbx.files_written[path] = content

        return _Files()

    @property
    def commands(self):
        class _Commands:
            def run(self, cmd, timeout=None):
                return SimpleNamespace(exit_code=0, stdout="sandbox-out\n", stderr="")

        return _Commands()


def _install_fake_e2b(monkeypatch):
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=_FakeSandbox))
    monkeypatch.setenv("E2B_API_KEY", "test-key")
    E2BCommandTarget._next_create_at = 0.0


def _e2b_spec(**raw):
    target_raw = {
        "type": "command",
        "command": "./agent",
        "sandbox": "e2b",
        "sandbox_create_interval": 0,
        **raw,
    }
    return TargetSpec(
        type="command",
        id="agent",
        raw=target_raw,
        cost=CostSpec(basis="per_second", per_second=0.001),
    )


def test_build_target_routes_sandbox_e2b():
    spec = _e2b_spec()
    assert isinstance(build_target(spec, PricingTable({})), E2BCommandTarget)
    local = TargetSpec(type="command", id="x", raw={"type": "command", "command": "cat"})
    assert isinstance(build_target(local, PricingTable({})), CommandTarget)


def test_e2b_target_measures_cost_and_stages_input(monkeypatch):
    _install_fake_e2b(monkeypatch)
    spec = _e2b_spec()
    out = E2BCommandTarget(spec).run(TaskSpec(), "hello")

    assert out.text == "sandbox-out"
    assert out.cost_basis == "e2b-sandbox-seconds"
    # measured: rate x observed latency, never a declared flat number
    assert out.cost == pytest.approx(0.001 * out.latency)
    assert "hello" in _FakeSandbox.last.files_written["/tmp/costbench_input"]
    assert _FakeSandbox.last.killed is True  # sandbox is torn down after the run


def test_e2b_target_missing_dependency_is_friendly(monkeypatch):
    # Force `import e2b` to fail deterministically whether or not e2b is
    # installed: None in sys.modules makes the import raise ImportError.
    monkeypatch.setitem(sys.modules, "e2b", None)
    monkeypatch.setenv("E2B_API_KEY", "test-key")
    spec = _e2b_spec()
    out = E2BCommandTarget(spec).run(TaskSpec(), "x")
    assert "pip install costbench[e2b]" in out.error


def test_e2b_target_requires_api_key(monkeypatch):
    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=_FakeSandbox))
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    spec = _e2b_spec()
    out = E2BCommandTarget(spec).run(TaskSpec(), "x")
    assert "E2B_API_KEY" in out.error


def test_e2b_target_paces_sandbox_creation(monkeypatch):
    _install_fake_e2b(monkeypatch)
    clock = [10.0]
    sleeps = []

    monkeypatch.setattr("costbench.targets.time.monotonic", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("costbench.targets.time.sleep", sleep)
    spec = _e2b_spec(sandbox_create_interval=1.0)
    target = E2BCommandTarget(spec)

    target.run(TaskSpec(), "first")
    target.run(TaskSpec(), "second")

    assert sleeps == [pytest.approx(1.0)]


def test_e2b_target_requires_explicit_combined_rate():
    spec = TargetSpec(
        type="command",
        id="agent",
        raw={"type": "command", "command": "./agent", "sandbox": "e2b"},
    )

    with pytest.raises(ValueError, match="combined per-second cost rate"):
        E2BCommandTarget(spec)
