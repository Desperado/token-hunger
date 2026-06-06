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

import base64
import json
import math
import os
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import MAX_E2B_SANDBOXES, CostSpec, TargetSpec, TaskSpec
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

    def prepare(self, concurrency: int, case_count: int) -> None:
        """Allocate resources shared across case calls."""
        return None

    def close(self) -> None:
        """Release resources allocated for this target."""
        return None

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
        self.params = dict(spec.raw.get("params", {}))
        # A benchmark case must correspond to one provider attempt. Implicit
        # SDK retries can turn one logical case into several billable calls
        # while only the final response's usage is visible to costbench.
        if "max_retries" not in self.params and "num_retries" not in self.params:
            self.params["max_retries"] = 0

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

    def __init__(self, spec: TargetSpec, pricing: PricingTable):
        self.spec = spec
        self.pricing = pricing
        self.url = spec.raw["url"]
        self.method = spec.raw.get("method", "POST").upper()
        self.headers = dict(spec.raw.get("headers", {}))
        self.request_template = spec.raw.get("request_template", {"input": "{input}"})
        self.response_path = spec.raw.get("response_path")
        self.input_tokens_path = spec.raw.get("input_tokens_path")
        self.output_tokens_path = spec.raw.get("output_tokens_path")
        self.cost_spec: CostSpec = spec.cost

    def _headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        auth_env = self.spec.raw.get("auth_env")
        if not auth_env:
            return headers
        token = os.environ.get(auth_env, "")
        scheme = self.spec.raw.get("auth_scheme", "bearer").lower()
        if scheme == "basic":
            token = base64.b64encode(token.encode("utf-8")).decode("ascii")
            value = f"Basic {token}"
        else:
            value = f"Bearer {token}"
        headers.setdefault("Authorization", value)
        return headers

    @staticmethod
    def _token_count(data: Any, path: Optional[str]) -> Optional[int]:
        if not path:
            return None
        value = _dig(data, path)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{path!r} must resolve to a non-negative integer")
        return value

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
        if (
            auth_env
            and self.spec.raw.get("auth_scheme", "bearer").lower() == "basic"
            and ":" not in os.environ[auth_env]
        ):
            return CaseOutput(
                text="",
                error=f"environment variable {auth_env!r} must use user:password format",
            )

        start = time.perf_counter()
        try:
            resp = httpx.request(
                self.method,
                self.url,
                json=body,
                headers=self._headers(),
                timeout=120.0,
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
            input_tokens = self._token_count(data, self.input_tokens_path)
            output_tokens = self._token_count(data, self.output_tokens_path)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return CaseOutput(text="", error=f"endpoint response mapping: {exc}",
                              cost=self.cost_spec.amortized_per_request(),
                              cost_basis=self.cost_spec.label,
                              latency=latency)

        cost = self.cost_spec.amortized_per_request()
        basis = self.cost_spec.label
        price = self.pricing.get(self.spec.id)
        if price and input_tokens is not None and output_tokens is not None:
            cost = price.cost(input_tokens, output_tokens)
            basis = price.cost_basis_label

        return CaseOutput(
            text=str(text),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            cost_basis=basis,
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


# Directory inside the sandbox where each case's input is staged so the command
# can read it on stdin, mirroring CommandTarget's stdin->stdout contract. Each
# case gets a *unique* filename here: a pooled sandbox is reused across cases,
# and re-writing one fixed path on a reused VM can fail with a permission error
# ("open /tmp/costbench_input: permission denied"), so we never reopen a file.
_E2B_INPUT_DIR = "/tmp"


@dataclass
class _E2BSandboxSlot:
    sandbox: Any
    started_at: float
    outputs: list[tuple[CaseOutput, float]] = field(default_factory=list)


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
        pool_size = spec.raw.get("sandbox_pool_size", MAX_E2B_SANDBOXES)
        if (
            not isinstance(pool_size, int)
            or isinstance(pool_size, bool)
            or not 1 <= pool_size <= MAX_E2B_SANDBOXES
        ):
            raise ValueError(
                f"sandbox_pool_size must be an integer between "
                f"1 and {MAX_E2B_SANDBOXES}"
            )
        self.pool_size = pool_size

        # Always run through the pool. Without prepare() the limit is 1 (a single
        # reused sandbox); the runner calls prepare() to raise it for concurrent
        # runs. One code path means cost is finalized identically at every
        # concurrency — no separate per-call model that bills different seconds.
        self._pool_limit = 1
        self._pool_condition = threading.Condition()
        self._available: list[_E2BSandboxSlot] = []
        self._slots: list[_E2BSandboxSlot] = []
        self._creating = 0
        self._closed = False

    def prepare(self, concurrency: int, case_count: int) -> None:
        self._pool_limit = min(
            self.pool_size,
            MAX_E2B_SANDBOXES,
            max(1, concurrency),
            max(1, case_count),
        )

    def close(self) -> None:
        # The runner calls close() only after the ThreadPoolExecutor has joined
        # every worker (see runner.run_benchmark), so no worker is mutating a
        # slot's `outputs` while we finalize it here. That join is what makes the
        # unlocked `slot.outputs.append` in _run_pooled safe — preserve it if the
        # lifecycle ever changes.
        with self._pool_condition:
            if self._closed:
                return
            self._closed = True
            slots = list(self._slots)
            self._available.clear()
            self._pool_condition.notify_all()

        for slot in slots:
            self._finalize_slot(slot)

    def _wait_for_create_slot(self) -> None:
        # Account-wide creation pacing. Reserve this thread's slot under the lock
        # and advance the shared cursor, then release the lock *before* sleeping
        # so other creators can reserve their own slots and sleep concurrently
        # (holding the lock across sleep would serialize the whole pool warm-up).
        # When targets declare different intervals the cursor reflects the most
        # recent reservation; mixed intervals are not individually guaranteed.
        cls = type(self)
        with cls._create_lock:
            slot_at = max(time.monotonic(), cls._next_create_at)
            cls._next_create_at = slot_at + self.create_interval
        delay = slot_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def _create_sandbox(self, sandbox_class: Any) -> _E2BSandboxSlot:
        self._wait_for_create_slot()
        started_at = time.perf_counter()
        sandbox = (
            sandbox_class.create(template=self.template)
            if self.template
            else sandbox_class.create()
        )
        return _E2BSandboxSlot(sandbox=sandbox, started_at=started_at)

    def _acquire_sandbox(self, sandbox_class: Any) -> _E2BSandboxSlot:
        while True:
            with self._pool_condition:
                if self._closed:
                    raise RuntimeError("e2b sandbox pool is closed")
                if self._available:
                    return self._available.pop()
                if len(self._slots) + self._creating < self._pool_limit:
                    self._creating += 1
                    break
                self._pool_condition.wait()

        try:
            slot = self._create_sandbox(sandbox_class)
        except Exception:
            with self._pool_condition:
                self._creating -= 1
                # notify_all, not notify: freeing creation capacity can satisfy a
                # waiter via the create branch, but a single notify could wake one
                # that then re-waits while another eligible waiter sleeps on.
                self._pool_condition.notify_all()
            raise

        with self._pool_condition:
            self._creating -= 1
            if self._closed:
                try:
                    slot.sandbox.kill()
                except Exception:  # noqa: BLE001
                    pass
                raise RuntimeError("e2b sandbox pool is closed")
            self._slots.append(slot)
            self._pool_condition.notify_all()
        return slot

    def _release_sandbox(self, slot: _E2BSandboxSlot) -> None:
        with self._pool_condition:
            if not self._closed:
                self._available.append(slot)
            # notify_all: a returned slot can satisfy a waiter via either the
            # available-slot branch or the create branch, so wake them all.
            self._pool_condition.notify_all()

    def _discard_sandbox(self, slot: _E2BSandboxSlot) -> None:
        with self._pool_condition:
            if slot in self._slots:
                self._slots.remove(slot)
            # notify_all: removing a slot frees creation capacity for any waiter.
            self._pool_condition.notify_all()
        self._finalize_slot(slot)

    def _finalize_slot(self, slot: _E2BSandboxSlot) -> None:
        try:
            slot.sandbox.kill()
        except Exception:  # noqa: BLE001 - best-effort remote cleanup
            pass
        ended_at = time.perf_counter()
        total_cost = self.cost_spec.cost_for_seconds(
            max(0.0, ended_at - slot.started_at)
        )
        if total_cost is None or not slot.outputs:
            return
        total_weight = sum(weight for _, weight in slot.outputs)
        if total_weight <= 0:
            share = total_cost / len(slot.outputs)
            for output, _ in slot.outputs:
                output.cost = share
            return
        for output, weight in slot.outputs:
            output.cost = total_cost * weight / total_weight

    def _execute(self, slot: _E2BSandboxSlot, payload: str) -> Any:
        # Fresh path per case so a reused sandbox never reopens a staged file.
        input_path = f"{_E2B_INPUT_DIR}/costbench_input_{uuid.uuid4().hex}"
        slot.sandbox.files.write(input_path, payload)
        shell = f"{self.command} < {shlex.quote(input_path)}"
        return slot.sandbox.commands.run(
            f"sh -c {shlex.quote(shell)}",
            timeout=self.timeout,
        )

    def _result(
        self,
        proc: Any,
        latency: float,
        cost: Optional[float],
    ) -> CaseOutput:
        """Build a CaseOutput from a command result *or* a non-zero-exit error.

        e2b carries exit_code/stdout/stderr on both the success object and the
        CommandExitException it raises, so one shape handles both.
        """
        exit_code = getattr(proc, "exit_code", 0) or 0
        stdout = (getattr(proc, "stdout", "") or "").strip()
        stderr = getattr(proc, "stderr", "") or ""
        err = None if exit_code == 0 else f"exit {exit_code}: {stderr.strip()[:200]}"
        return CaseOutput(
            text=stdout, error=err, cost=cost,
            cost_basis=self.cost_spec.label, latency=latency,
        )

    def _payload(self, task: TaskSpec, case_input: str) -> str:
        rendered = _render_prompt(task, case_input)
        if task.system:
            return json.dumps({"system": task.system, "input": rendered})
        return rendered

    def _run_pooled(self, sandbox_class: Any, payload: str) -> CaseOutput:
        started_at = time.perf_counter()
        try:
            slot = self._acquire_sandbox(sandbox_class)
        except Exception as exc:  # noqa: BLE001
            latency = time.perf_counter() - started_at
            # cost is None, not 0.0: a failed acquire may have partially spun up
            # a billed sandbox, so the real cost is unknown — never report $0 for
            # "we don't know" (that would deflate cost-per-success silently).
            return CaseOutput(
                text="",
                error=f"{type(exc).__name__}: {exc}",
                cost=None,
                cost_basis=self.cost_spec.label,
                latency=latency,
            )

        active_at = time.perf_counter()
        proc = None
        failure = None
        try:
            proc = self._execute(slot, payload)
        except Exception as exc:  # noqa: BLE001
            failure = exc
        active_seconds = max(0.0, time.perf_counter() - active_at)
        latency = time.perf_counter() - started_at

        if failure is not None and getattr(failure, "exit_code", None) is None:
            output = CaseOutput(
                text="",
                error=f"{type(failure).__name__}: {failure}",
                cost=None,
                cost_basis=self.cost_spec.label,
                latency=latency,
            )
        else:
            output = self._result(
                failure if failure is not None else proc,
                latency,
                cost=None,
            )
        slot.outputs.append((output, active_seconds))
        if failure is not None and getattr(failure, "exit_code", None) is None:
            self._discard_sandbox(slot)
        else:
            self._release_sandbox(slot)
        return output

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

        payload = self._payload(task, case_input)
        return self._run_pooled(Sandbox, payload)


# TODO(v2): native local_model target wrapping an ollama/vLLM server. Today,
# serve local models as a `model` target via litellm (ollama/... or an
# OpenAI-compatible localhost endpoint) or as a `command`/`endpoint` target.


def build_target(spec: TargetSpec, pricing: PricingTable) -> Target:
    if spec.type == "model":
        return ModelTarget(spec, pricing)
    if spec.type == "endpoint":
        return EndpointTarget(spec, pricing)
    if spec.type == "command":
        if spec.raw.get("sandbox") == "e2b":
            return E2BCommandTarget(spec)
        return CommandTarget(spec)
    raise ValueError(f"unknown target type: {spec.type!r}")
