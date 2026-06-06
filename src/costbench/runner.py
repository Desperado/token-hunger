"""Run the benchmark and aggregate results.

For every (target, case) pair: produce an output, check correctness, record
cost and latency. Then aggregate per target into the numbers that matter — and
the only headline that tells the truth is **cost per success**.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from .checks import make_check
from .config import Config
from .pricing import load_pricing
from .targets import CaseOutput, Target, build_target


@dataclass
class CaseResult:
    case_input: str
    expect: object
    output: str
    passed: bool
    detail: str
    cost: Optional[float]
    cost_basis: str
    latency: float
    error: Optional[str] = None
    # Observed token usage (when the target can report it). Additive, defaults
    # None, so no caller breaks; consumed by the calibration-history write hook.
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


@dataclass
class TargetResult:
    target_id: str
    target_type: str
    cost_note: Optional[str] = None
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.cases)

    @property
    def errors(self) -> int:
        return sum(1 for c in self.cases if c.error)

    @property
    def passes(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.n if self.n else 0.0

    @property
    def n_priced(self) -> int:
        return sum(1 for c in self.cases if c.cost is not None)

    @property
    def n_unpriced(self) -> int:
        return self.n - self.n_priced

    @property
    def cost_known(self) -> bool:
        """True if AT LEAST ONE case has a known cost."""
        return self.n_priced > 0

    @property
    def total_cost(self) -> Optional[float]:
        """Sum of KNOWN per-case costs. None only if nothing is priced."""
        if self.n_priced == 0:
            return None
        return sum(c.cost for c in self.cases if c.cost is not None)

    @property
    def cost_per_run(self) -> Optional[float]:
        """Total known cost divided by number of PRICED cases (not n).

        Divides by n_priced so the per-run figure is the average cost of the
        cases we could actually price — it is not deflated by unpriced cases."""
        total = self.total_cost
        return total / self.n_priced if total is not None and self.n_priced else None

    @property
    def cost_per_success(self) -> Optional[float]:
        """Total KNOWN cost divided by number of correct outputs. The headline.

        Returns None if nothing is priced; float('inf') if nothing passed (you
        paid and got zero correct answers — honestly infinite cost/success)."""
        total = self.total_cost
        if total is None:
            return None
        if self.passes == 0:
            return float("inf")
        return total / self.passes

    @property
    def cost_basis(self) -> str:
        bases = {c.cost_basis for c in self.cases}
        return next(iter(bases)) if len(bases) == 1 else "mixed"

    @property
    def mean_latency(self) -> float:
        return sum(c.latency for c in self.cases) / self.n if self.n else 0.0


@dataclass
class BenchmarkReport:
    name: str
    fingerprint: str
    results: list[TargetResult]
    pricing_fingerprint: str = ""

    def ranked_by_cost_per_success(self) -> list[TargetResult]:
        def key(r: TargetResult):
            cps = r.cost_per_success
            return (cps is None, cps if cps is not None else 0.0)

        return sorted(self.results, key=key)


ProgressFn = Callable[[str, int, int], None]


def run_benchmark(
    config: Config,
    concurrency: int = 4,
    progress: Optional[ProgressFn] = None,
) -> BenchmarkReport:
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    pricing = load_pricing(config.pricing_path).with_overrides(config.pricing_overrides)
    default_check = make_check(config.check)

    results: list[TargetResult] = []
    for spec in config.targets:
        target: Target = build_target(spec, pricing)
        tr = TargetResult(
            target_id=spec.id,
            target_type=spec.type,
            cost_note=spec.cost.assumption,
        )

        def run_case(case):
            out: CaseOutput = target.run(config.task, case.input)
            check = make_check(case.check) if case.check else default_check
            if out.error:
                return CaseResult(case.input, case.expect, out.text, False,
                                  out.error, out.cost, out.cost_basis, out.latency,
                                  error=out.error,
                                  input_tokens=out.input_tokens,
                                  output_tokens=out.output_tokens)
            verdict = check(out.text, case.expect)
            return CaseResult(case.input, case.expect, out.text, verdict.passed,
                              verdict.detail, out.cost, out.cost_basis, out.latency,
                              input_tokens=out.input_tokens,
                              output_tokens=out.output_tokens)

        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                case_results = list(pool.map(run_case, config.cases))
        else:
            case_results = [run_case(c) for c in config.cases]

        tr.cases = case_results
        results.append(tr)
        if progress:
            progress(spec.id, tr.passes, tr.n)

    return BenchmarkReport(
        name=config.name,
        fingerprint=config.fingerprint,
        results=results,
        pricing_fingerprint=pricing.fingerprint,
    )
