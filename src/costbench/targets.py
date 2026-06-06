"""Target adapters.

A *target* is anything that takes the task input and returns an output. The
benchmark doesn't care what's behind it — a raw model, an HTTP API (a SaaS
orchestrator, a competitor, your own RAG pipeline), or a local command. Each
adapter returns a :class:`CaseOutput` with the text, the token usage (when
knowable), and a cost basis, so the runner can score them all on the same field.

litellm and httpx are imported lazily so the package installs and unit-tests
run without them; they're only needed when you actually use a model/endpoint.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from .config import CostSpec, TargetSpec, TaskSpec
from .pricing import AmortizedGpuPrice, PricingTable


@dataclass
class CaseOutput:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost: Optional[float] = None
    cost_basis: str = "unknown"
    latency: float = 0.0
    error: Optional[str] = None


def _render_prompt(task: TaskSpec, case_input: str) -> str:
    return task.prompt_template.replace("{input}", case_input)


def _dig(obj: Any, path: str) -> Any:
    """Follow a dotted path like 'result.answer' or 'choices.0.text'."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def _fill_template(template: Any, value: str) -> Any:
    """Recursively replace the '{input}' placeholder inside a JSON-ish body."""
    if isinstance(template, str):
        return template.replace("{input}", value)
    if isinstance(template, dict):
        return {k: _fill_template(v, value) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill_template(v, value) for v in template]
    return template


class Target:
    spec: TargetSpec

    def run(self, task: TaskSpec, case_input: str) -> CaseOutput:  # pragma: no cover
        raise NotImplementedError

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def type(self) -> str:
        return self.spec.type


class ModelTarget(Target):
    """A raw model called via litellm. Cost = tokens × committed price table."""

    def __init__(self, spec: TargetSpec, pricing: PricingTable):
        self.spec = spec
        self.pricing = pricing
        self.model = spec.raw.get("model", spec.id)
        self.params = spec.raw.get("params", {})

    def run(self, task: TaskSpec, case_input: str) -> CaseOutput:
        try:
            import litellm  # lazy
        except ModuleNotFoundError:
            return CaseOutput(
                text="",
                error="model targets need the optional dependency: pip install costbench[models]",
            )

        messages = []
        if task.system:
            messages.append({"role": "system", "content": task.system})
        messages.append({"role": "user", "content": _render_prompt(task, case_input)})

        start = time.perf_counter()
        try:
            resp = litellm.completion(
                model=self.model, messages=messages, **self.params
            )
        except Exception as exc:  # noqa: BLE001 — surface provider errors per-case
            return CaseOutput(text="", error=f"{type(exc).__name__}: {exc}",
                              latency=time.perf_counter() - start)
        latency = time.perf_counter() - start

        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", None) if usage else None
        out_tok = getattr(usage, "completion_tokens", None) if usage else None

        cost, basis = None, "unknown"
        price = self.pricing.get(self.spec.id)
        if isinstance(price, AmortizedGpuPrice) and self.spec.infra_cost is not None:
            price = price.with_infra(
                gpu_hourly_rate=self.spec.infra_cost.gpu_hourly_rate,
                throughput_tokens_per_sec=(
                    self.spec.infra_cost.throughput_tokens_per_sec
                ),
            )
        if price and in_tok is not None and out_tok is not None:
            cost = price.cost(in_tok, out_tok)
            basis = price.cost_basis_label
        elif in_tok is not None:
            basis = "tokens (no price in table)"

        return CaseOutput(text=text, input_tokens=in_tok, output_tokens=out_tok,
                          cost=cost, cost_basis=basis, latency=latency)


class EndpointTarget(Target):
    """Any HTTP service: a SaaS orchestrator, a competitor, a custom pipeline.

    Cost can't be derived from tokens we can't see, so it's declared in the
    config and reported with its basis — never blended with per-token numbers.
    """

    def __init__(self, spec: TargetSpec):
        self.spec = spec
        self.url = spec.raw["url"]
        self.method = spec.raw.get("method", "POST").upper()
        self.headers = dict(spec.raw.get("headers", {}))
        auth_env = spec.raw.get("auth_env")
        if auth_env:
            token = os.environ.get(auth_env, "")
            self.headers.setdefault("Authorization", f"Bearer {token}")
        self.request_template = spec.raw.get("request_template", {"input": "{input}"})
        self.response_path = spec.raw.get("response_path")
        self.cost_spec: CostSpec = spec.cost

    def run(self, task: TaskSpec, case_input: str) -> CaseOutput:
        try:
            import httpx  # lazy
        except ModuleNotFoundError:
            return CaseOutput(
                text="",
                error="endpoint targets need the optional dependency: pip install costbench[endpoint]",
            )

        rendered_input = _render_prompt(task, case_input)
        body = _fill_template(self.request_template, rendered_input)
        auth_env = self.spec.raw.get("auth_env")
        if auth_env and not os.environ.get(auth_env):
            return CaseOutput(
                text="",
                error=f"environment variable {auth_env!r} is not set",
            )

        start = time.perf_counter()
        try:
            resp = httpx.request(
                self.method, self.url, json=body, headers=self.headers, timeout=120.0
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return CaseOutput(text="", error=f"{type(exc).__name__}: {exc}",
                              cost=self.cost_spec.amortized_per_request(),
                              cost_basis=self.cost_spec.label,
                              latency=time.perf_counter() - start)
        latency = time.perf_counter() - start

        try:
            text = _dig(data, self.response_path) if self.response_path else data
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return CaseOutput(text="", error=f"response_path {self.response_path!r}: {exc}",
                              cost=self.cost_spec.amortized_per_request(),
                              cost_basis=self.cost_spec.label,
                              latency=latency)

        return CaseOutput(
            text=str(text),
            cost=self.cost_spec.amortized_per_request(),
            cost_basis=self.cost_spec.label,
            latency=latency,
        )


class CommandTarget(Target):
    """A local command/script: input on stdin, output on stdout.

    Lets you benchmark a homegrown pipeline with no HTTP layer. Cost is whatever
    you declare (often 'unknown' for local infra).

    The command comes from the user's local benchmark config and is intentionally
    executable. A string uses ``/bin/sh -c`` to support pipelines/redirection;
    use the list form for direct ``shell=False`` execution. Never run an
    untrusted config locally; use ``sandbox: e2b`` for untrusted code.
    """

    def __init__(self, spec: TargetSpec):
        self.spec = spec
        cmd = spec.raw["command"]
        self.command = cmd if isinstance(cmd, list) else ["/bin/sh", "-c", cmd]
        self.cost_spec: CostSpec = spec.cost

    def run(self, task: TaskSpec, case_input: str) -> CaseOutput:
        rendered = _render_prompt(task, case_input)
        payload = rendered
        if task.system:
            payload = json.dumps({"system": task.system, "input": rendered})

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                self.command, input=payload, capture_output=True, text=True, timeout=120
            )
        except Exception as exc:  # noqa: BLE001
            return CaseOutput(text="", error=f"{type(exc).__name__}: {exc}",
                              cost=self.cost_spec.amortized_per_request(),
                              cost_basis=self.cost_spec.label,
                              latency=time.perf_counter() - start)
        latency = time.perf_counter() - start

        if proc.returncode != 0:
            return CaseOutput(text=proc.stdout.strip(),
                              error=f"exit {proc.returncode}: {proc.stderr.strip()[:200]}",
                              cost=self.cost_spec.amortized_per_request(),
                              cost_basis=self.cost_spec.label,
                              latency=latency)

        return CaseOutput(
            text=proc.stdout.strip(),
            cost=self.cost_spec.amortized_per_request(),
            cost_basis=self.cost_spec.label,
            latency=latency,
        )


# Where we stage the case input inside the sandbox so the command can read it
# on stdin, mirroring CommandTarget's stdin->stdout contract.
_E2B_INPUT_PATH = "/tmp/costbench_input"


class E2BCommandTarget(Target):
    """A command run inside an e2b cloud sandbox (isolated Firecracker microVM).

    Same stdin->stdout contract as :class:`CommandTarget`, but the code runs off
    your machine and the cost basis is *measured* rather than declared: billed
    sandbox seconds x rate. Use it to (a) benchmark untrusted/external pipelines
    safely and (b) get a real infra cost for `command` targets instead of an
    'unknown'. Opt in per target with ``sandbox: e2b`` in the config.

    Needs E2B_API_KEY in the environment and the optional ``e2b`` dependency.
    """

    _create_lock = threading.Lock()
    _next_create_at = 0.0

    def __init__(self, spec: TargetSpec):
        self.spec = spec
        cmd = spec.raw["command"]
        # Sandbox execution goes through a shell so stdin redirection works;
        # normalize a list form to a single shell string.
        self.command = cmd if isinstance(cmd, str) else shlex.join(cmd)
        self.template = spec.raw.get("sandbox_template")  # optional e2b template id
        self.timeout = int(spec.raw.get("timeout", 120))
        self.cost_spec: CostSpec = spec.cost
        if self.cost_spec.basis != "per_second" or self.cost_spec.per_second is None:
            raise ValueError(
                "e2b command targets require a combined per-second cost rate"
            )
        # Hobby accounts allow one sandbox creation per second. Paid tiers can
        # lower this interval explicitly while retaining account-wide pacing.
        self.create_interval = float(spec.raw.get("sandbox_create_interval", 1.0))
        if not math.isfinite(self.create_interval) or self.create_interval < 0:
            raise ValueError(
                "sandbox_create_interval must be a finite non-negative number"
            )

    def _wait_for_create_slot(self) -> None:
        cls = type(self)
        with cls._create_lock:
            now = time.monotonic()
            wait = max(0.0, cls._next_create_at - now)
            if wait:
                time.sleep(wait)
            created_at = time.monotonic()
            cls._next_create_at = created_at + self.create_interval

    def _result(self, proc: Any, latency: float) -> CaseOutput:
        """Build a CaseOutput from a command result *or* a non-zero-exit error.

        e2b carries exit_code/stdout/stderr on both the success object and the
        CommandExitException it raises, so one shape handles both.
        """
        exit_code = getattr(proc, "exit_code", 0) or 0
        stdout = (getattr(proc, "stdout", "") or "").strip()
        stderr = getattr(proc, "stderr", "") or ""
        err = None if exit_code == 0 else f"exit {exit_code}: {stderr.strip()[:200]}"
        return CaseOutput(
            text=stdout, error=err, cost=self.cost_spec.cost_for_seconds(latency),
            cost_basis="e2b-sandbox-seconds", latency=latency,
        )

    def run(self, task: TaskSpec, case_input: str) -> CaseOutput:
        try:
            from e2b import Sandbox  # lazy: optional dependency
        except ImportError:
            return CaseOutput(
                text="",
                error="e2b command targets need the optional dependency: pip install costbench[e2b]",
            )
        if not os.environ.get("E2B_API_KEY"):
            return CaseOutput(
                text="", error="environment variable 'E2B_API_KEY' is not set"
            )

        rendered = _render_prompt(task, case_input)
        payload = rendered
        if task.system:
            payload = json.dumps({"system": task.system, "input": rendered})

        self._wait_for_create_slot()
        start = time.perf_counter()
        sbx = None
        proc = None
        failure = None
        try:
            sbx = (
                Sandbox.create(template=self.template)
                if self.template
                else Sandbox.create()
            )
            sbx.files.write(_E2B_INPUT_PATH, payload)
            # Run through a shell so the command can read the case on stdin.
            shell = f"{self.command} < {_E2B_INPUT_PATH}"
            proc = sbx.commands.run(f"sh -c {shlex.quote(shell)}", timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 — surface sandbox errors per-case
            failure = exc
        finally:
            if sbx is not None:
                try:
                    sbx.kill()
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    pass
        latency = time.perf_counter() - start

        if failure is not None:
            # Non-zero exit comes back as an exception carrying the streams.
            if getattr(failure, "exit_code", None) is not None:
                return self._result(failure, latency)
            return CaseOutput(
                text="", error=f"{type(failure).__name__}: {failure}",
                cost=self.cost_spec.cost_for_seconds(latency),
                cost_basis="e2b-sandbox-seconds", latency=latency,
            )
        return self._result(proc, latency)


# TODO(v2): native local_model target wrapping an ollama/vLLM server. Today,
# serve local models as a `model` target via litellm (ollama/... or an
# OpenAI-compatible localhost endpoint) or as a `command`/`endpoint` target.


def build_target(spec: TargetSpec, pricing: PricingTable) -> Target:
    if spec.type == "model":
        return ModelTarget(spec, pricing)
    if spec.type == "endpoint":
        return EndpointTarget(spec)
    if spec.type == "command":
        if spec.raw.get("sandbox") == "e2b":
            return E2BCommandTarget(spec)
        return CommandTarget(spec)
    raise ValueError(f"unknown target type: {spec.type!r}")
