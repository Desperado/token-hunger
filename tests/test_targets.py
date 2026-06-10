import base64
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from costbench.config import CostSpec, InfraCost, TargetSpec, TaskSpec
from costbench.pricing import AmortizedGpuPrice, PricingTable
from costbench.targets import (
    CaseOutput,
    CommandTarget,
    E2BCommandTarget,
    EndpointTarget,
    ModelTarget,
    _E2BSandboxSlot,
    build_target,
)


def _endpoint_spec(**raw):
    base = {"type": "endpoint", "id": "svc", "url": "https://box.example/api/generate"}
    base.update(raw)
    return TargetSpec(type="endpoint", id=base["id"], raw=base,
                      cost=CostSpec(basis="unknown"))


def test_endpoint_bearer_auth_is_the_default(monkeypatch):
    monkeypatch.setenv("SVC_TOKEN", "sekret")
    target = EndpointTarget(_endpoint_spec(auth_env="SVC_TOKEN"))
    assert target.headers["Authorization"] == "Bearer sekret"


def test_endpoint_basic_auth_base64_encodes_user_pass(monkeypatch):
    monkeypatch.setenv("OLLAMA_AUTH", "user:pass")
    target = EndpointTarget(_endpoint_spec(auth_type="basic", auth_env="OLLAMA_AUTH"))
    expected = "Basic " + base64.b64encode(b"user:pass").decode("ascii")
    assert target.headers["Authorization"] == expected


def test_endpoint_unknown_auth_type_rejected():
    with pytest.raises(ValueError, match="auth_type"):
        EndpointTarget(_endpoint_spec(auth_type="digest", auth_env="X"))


def test_endpoint_basic_auth_request_roundtrip(monkeypatch):
    monkeypatch.setenv("OLLAMA_AUTH", "u:p")
    sent = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "1024"}

    def fake_request(method, url, json=None, headers=None, timeout=None):
        sent.update(method=method, url=url, json=json, headers=headers)
        return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(request=fake_request))

    target = EndpointTarget(_endpoint_spec(
        auth_type="basic",
        auth_env="OLLAMA_AUTH",
        request_template={"model": "qwen-coder", "prompt": "{input}", "stream": False},
        response_path="response",
    ))
    out = target.run(TaskSpec(), "What is 2 ** 10?")

    assert out.text == "1024"
    assert sent["headers"]["Authorization"].startswith("Basic ")
    assert sent["json"] == {"model": "qwen-coder", "prompt": "What is 2 ** 10?", "stream": False}


def test_endpoint_missing_auth_env_errors_without_calling(monkeypatch):
    monkeypatch.delenv("OLLAMA_AUTH", raising=False)

    def boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("endpoint should not be called when auth env is unset")

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(request=boom))
    target = EndpointTarget(_endpoint_spec(auth_type="basic", auth_env="OLLAMA_AUTH"))
    out = target.run(TaskSpec(), "x")
    assert "OLLAMA_AUTH" in out.error and out.text == ""


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
    assert calls[0]["max_retries"] == 0


def test_model_target_preserves_explicit_retry_setting(monkeypatch):
    calls = []
    fake_litellm = SimpleNamespace(
        completion=lambda **kwargs: calls.append(kwargs) or _response()
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    spec = TargetSpec(
        type="model",
        id="anthropic/claude-haiku-4-5",
        raw={
            "type": "model",
            "id": "anthropic/claude-haiku-4-5",
            "params": {"max_retries": 2},
        },
    )

    ModelTarget(spec, PricingTable({})).run(TaskSpec(), "hello")

    assert calls[0]["max_retries"] == 2


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
    instances = []

    def __init__(self):
        self.files_written = {}
        self.killed = False
        _FakeSandbox.last = self
        _FakeSandbox.instances.append(self)

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
    _FakeSandbox.instances = []


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


def test_e2b_target_stages_input_and_finalizes_cost_on_close(monkeypatch):
    _install_fake_e2b(monkeypatch)
    target = E2BCommandTarget(_e2b_spec())
    out = target.run(TaskSpec(), "hello")

    assert out.text == "sandbox-out"
    # honest basis: seconds are observed, the rate is user-declared
    assert out.cost_basis == "e2b-seconds × declared-rate"
    # input is staged to a unique /tmp path per case (reused-sandbox safe)
    staged = _FakeSandbox.last.files_written
    assert len(staged) == 1
    [(path, content)] = staged.items()
    assert path.startswith("/tmp/costbench_input_") and "hello" in content
    # cost is finalized from the sandbox's full lifetime at close(), not per call
    assert out.cost is None
    assert _FakeSandbox.last.killed is False

    target.close()

    assert _FakeSandbox.last.killed is True  # sandbox torn down on close
    assert out.cost is not None and out.cost >= 0


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
    # A worker that always fails (no exit_code) is discarded after each run, so
    # two sequential runs force two *creations* — letting us observe the
    # account-wide 1/sec creation pacing between them.
    clock = [10.0]
    sleeps = []

    monkeypatch.setattr("costbench.targets.time.monotonic", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("costbench.targets.time.sleep", sleep)

    class _BrokenSandbox(_FakeSandbox):
        @property
        def commands(self):
            class _Commands:
                def run(self, cmd, timeout=None):
                    raise RuntimeError("disconnected")

            return _Commands()

    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=_BrokenSandbox))
    monkeypatch.setenv("E2B_API_KEY", "test-key")
    E2BCommandTarget._next_create_at = 0.0

    target = E2BCommandTarget(_e2b_spec(sandbox_create_interval=1.0))
    target.run(TaskSpec(), "first")
    target.run(TaskSpec(), "second")

    assert sleeps == [pytest.approx(1.0)]


def test_e2b_finalize_allocates_lifetime_cost_proportionally(monkeypatch):
    _install_fake_e2b(monkeypatch)
    target = E2BCommandTarget(_e2b_spec())  # per_second rate 0.001
    o1 = CaseOutput(text="a", cost=None)
    o2 = CaseOutput(text="b", cost=None)
    slot = _E2BSandboxSlot(sandbox=_FakeSandbox.create(), started_at=100.0)
    slot.outputs = [(o1, 1.0), (o2, 3.0)]
    # lifetime = 110 - 100 = 10s; total cost = 0.001 * 10 = 0.01, split 1:3
    monkeypatch.setattr("costbench.targets.time.perf_counter", lambda: 110.0)

    target._finalize_slot(slot)

    assert slot.sandbox.killed is True
    assert o1.cost + o2.cost == pytest.approx(0.01)  # sums to full lifetime cost
    assert o1.cost == pytest.approx(0.0025)
    assert o2.cost == pytest.approx(0.0075)


def test_e2b_target_requires_explicit_combined_rate():
    spec = TargetSpec(
        type="command",
        id="agent",
        raw={"type": "command", "command": "./agent", "sandbox": "e2b"},
    )

    with pytest.raises(ValueError, match="combined per-second cost rate"):
        E2BCommandTarget(spec)


def test_e2b_target_reuses_pool_and_finalizes_full_lifetime_cost(monkeypatch):
    _install_fake_e2b(monkeypatch)
    target = E2BCommandTarget(_e2b_spec(sandbox_pool_size=10))
    target.prepare(concurrency=10, case_count=20)

    first = target.run(TaskSpec(), "first")
    second = target.run(TaskSpec(), "second")

    assert len(_FakeSandbox.instances) == 1
    assert _FakeSandbox.instances[0].killed is False
    assert first.cost is None
    assert second.cost is None

    target.close()

    assert _FakeSandbox.instances[0].killed is True
    assert first.cost is not None and first.cost >= 0
    assert second.cost is not None and second.cost >= 0
    assert first.cost + second.cost > 0


def test_e2b_reused_sandbox_stages_unique_input_paths(monkeypatch):
    # Regression: a fixed staging path failed with "permission denied" when a
    # pooled sandbox was reused; each case must write a distinct path.
    _install_fake_e2b(monkeypatch)
    target = E2BCommandTarget(_e2b_spec(sandbox_pool_size=1))
    target.prepare(concurrency=1, case_count=2)
    target.run(TaskSpec(), "first")
    target.run(TaskSpec(), "second")
    target.close()

    assert len(_FakeSandbox.instances) == 1  # the same sandbox was reused
    staged = _FakeSandbox.instances[0].files_written
    assert len(staged) == 2  # one fresh input file per case, never reopened
    assert all(p.startswith("/tmp/costbench_input_") for p in staged)


def test_e2b_target_pool_is_capped_at_ten():
    target = E2BCommandTarget(_e2b_spec(sandbox_pool_size=10))

    target.prepare(concurrency=32, case_count=100)

    assert target._pool_limit == 10


def test_e2b_target_runs_twenty_cases_with_at_most_ten_sandboxes(monkeypatch):
    _install_fake_e2b(monkeypatch)
    barrier = threading.Barrier(10)

    class _ConcurrentSandbox(_FakeSandbox):
        @property
        def commands(self):
            class _Commands:
                def run(self, cmd, timeout=None):
                    barrier.wait(timeout=2)
                    time.sleep(0.01)
                    return SimpleNamespace(
                        exit_code=0,
                        stdout="sandbox-out\n",
                        stderr="",
                    )

            return _Commands()

    monkeypatch.setitem(
        sys.modules,
        "e2b",
        SimpleNamespace(Sandbox=_ConcurrentSandbox),
    )
    target = E2BCommandTarget(_e2b_spec(sandbox_pool_size=10))
    target.prepare(concurrency=10, case_count=20)

    with ThreadPoolExecutor(max_workers=10) as pool:
        outputs = list(
            pool.map(lambda i: target.run(TaskSpec(), str(i)), range(20))
        )
    target.close()

    assert len(_FakeSandbox.instances) == 10
    assert all(sandbox.killed for sandbox in _FakeSandbox.instances)
    assert all(output.text == "sandbox-out" for output in outputs)
    assert all(output.cost is not None for output in outputs)


def test_e2b_target_retires_broken_sandbox_worker(monkeypatch):
    _install_fake_e2b(monkeypatch)
    calls = [RuntimeError("sandbox disconnected"), SimpleNamespace(
        exit_code=0,
        stdout="recovered\n",
        stderr="",
    )]

    class _RecoveringSandbox(_FakeSandbox):
        @property
        def commands(self):
            class _Commands:
                def run(self, cmd, timeout=None):
                    result = calls.pop(0)
                    if isinstance(result, Exception):
                        raise result
                    return result

            return _Commands()

    monkeypatch.setitem(
        sys.modules,
        "e2b",
        SimpleNamespace(Sandbox=_RecoveringSandbox),
    )
    target = E2BCommandTarget(_e2b_spec(sandbox_pool_size=1))
    target.prepare(concurrency=1, case_count=2)

    first = target.run(TaskSpec(), "first")
    second = target.run(TaskSpec(), "second")
    target.close()

    assert "sandbox disconnected" in first.error
    assert second.text == "recovered"
    assert len(_FakeSandbox.instances) == 2
    assert all(sandbox.killed for sandbox in _FakeSandbox.instances)
