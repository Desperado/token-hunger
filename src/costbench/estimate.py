"""`costbench estimate` engine — predict cost BEFORE you spend.

Keyless, no network, no target execution. Per target we compute:
  - input cost from a request-aware tokenizer estimate, and
  - output cost as a RANGE: a worst-case ceiling from max_output_tokens, or a
    calibrated p50–p90 range once enough run history exists.

Everything rounds UP — surprising a user with a higher bill is the cardinal sin.
Estimates carry the basis `estimated (...)` and never blend with verified
$/token run costs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .config import Config, TargetSpec
from .history import Observation, TokenPercentiles, percentiles_for
from .limits import DEFAULT_MAX_OUTPUT_TOKENS
from .pricing import AmortizedGpuPrice, PricingTable
from .targets import _render_prompt
from .tokens import count_chat_input_tokens


@dataclass(frozen=True)
class CaseEstimate:
    input_tokens: int
    input_exact: bool
    output_ceiling: int
    input_cost: float
    output_cost_ceiling: float
    method: str


@dataclass(frozen=True)
class TargetEstimate:
    target_id: str
    target_type: str
    n_cases: int
    priced: bool
    cost_basis: str
    input_cost_total: Optional[float]
    output_cost_low: Optional[float]
    output_cost_high: Optional[float]
    per_case_low: Optional[float]
    per_case_high: Optional[float]
    note: Optional[str] = None
    calibrated: bool = False
    tokenizer_method: str = ""
    input_exact: bool = False
    output_ceiling: int = 0
    ceiling_source: str = ""
    # Token totals across all cases (None for black-box targets whose tokens are
    # not observable). Exposed so a UI can show counts, not just costs.
    input_tokens_total: Optional[int] = None
    output_tokens_low: Optional[int] = None
    output_tokens_high: Optional[int] = None


def _round_up(value: float, places: int = 6) -> float:
    factor = 10 ** places
    return math.ceil(value * factor) / factor


def _resolve_output_ceiling(
    spec: TargetSpec, limits: dict[str, dict], max_output_override: Optional[int]
) -> tuple[int, str]:
    """Worst-case output ceiling, in priority order. Returns (value, source)."""
    if max_output_override is not None:
        return _positive_ceiling(
            max_output_override,
            "CLI --max-output-tokens",
        )
    params = spec.raw.get("params", {}) or {}
    for param_name in ("max_tokens", "max_completion_tokens"):
        if params.get(param_name) is not None:
            return _positive_ceiling(
                params[param_name],
                f"config params.{param_name}",
            )
    entry = limits.get(spec.id)
    if entry and entry.get("max_output_tokens") is not None:
        return _positive_ceiling(
            entry["max_output_tokens"],
            "model_limits.yaml",
        )
    return DEFAULT_MAX_OUTPUT_TOKENS, f"default ({DEFAULT_MAX_OUTPUT_TOKENS})"


def _positive_ceiling(value, source: str) -> tuple[int, str]:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{source} must be a positive integer") from exc
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric <= 0:
        raise ValueError(f"{source} must be a positive integer")
    return int(numeric), source


def _apply_infra(price, spec: TargetSpec):
    """Apply per-target infra_cost overrides to an amortized-GPU price."""
    if isinstance(price, AmortizedGpuPrice) and spec.infra_cost is not None:
        return price.with_infra(
            gpu_hourly_rate=spec.infra_cost.gpu_hourly_rate,
            throughput_tokens_per_sec=spec.infra_cost.throughput_tokens_per_sec,
        )
    return price


def _estimate_model_target(
    spec: TargetSpec,
    config: Config,
    pricing: PricingTable,
    limits: dict[str, dict],
    history: Optional[list[Observation]],
    max_output_override: Optional[int],
) -> TargetEstimate:
    n = len(config.cases)
    price = pricing.get(spec.id)
    if price is None:
        return TargetEstimate(
            target_id=spec.id,
            target_type=spec.type,
            n_cases=n,
            priced=False,
            cost_basis="estimated (no price in table)",
            input_cost_total=None,
            output_cost_low=None,
            output_cost_high=None,
            per_case_low=None,
            per_case_high=None,
            note=f"no price for {spec.id!r} in the pricing table — add it to "
            f"pricing.yaml or a 'pricing:' block to estimate this target.",
        )
    price = _apply_infra(price, spec)

    ceiling, ceiling_source = _resolve_output_ceiling(spec, limits, max_output_override)

    input_tokens_total = 0
    method = ""
    input_exact = True
    for case in config.cases:
        prompt = _render_prompt(config.task, case.input)
        tc = count_chat_input_tokens(
            config.task.system,
            prompt,
            spec.id,
            spec.raw.get("params"),
        )
        input_tokens_total += tc.tokens
        method = tc.method
        input_exact = input_exact and tc.exact

    input_cost_total = _round_up(_cost_for_tokens(price, input_tokens_total, 0))

    # output range
    pcts: Optional[TokenPercentiles] = None
    if history is not None:
        pcts = percentiles_for(history, config.fingerprint, spec.id)

    if pcts is not None:
        low_out = pcts.output_p50 * n
        high_out = pcts.output_p90 * n
        output_cost_low = _round_up(_cost_for_tokens(price, 0, low_out))
        output_cost_high = _round_up(_cost_for_tokens(price, 0, high_out))
        output_tokens_low = int(math.ceil(low_out))
        output_tokens_high = int(math.ceil(high_out))
        calibrated = True
        cost_basis = "estimated (calibrated p50–p90)"
    else:
        out_total = ceiling * n
        ceil_cost = _round_up(_cost_for_tokens(price, 0, out_total))
        output_cost_low = ceil_cost
        output_cost_high = ceil_cost
        output_tokens_low = out_total
        output_tokens_high = out_total
        calibrated = False
        cost_basis = "estimated (worst-case ceiling)"

    low_total = input_cost_total + output_cost_low
    high_total = input_cost_total + output_cost_high
    return TargetEstimate(
        target_id=spec.id,
        target_type=spec.type,
        n_cases=n,
        priced=True,
        cost_basis=cost_basis,
        input_cost_total=input_cost_total,
        output_cost_low=output_cost_low,
        output_cost_high=output_cost_high,
        per_case_low=_round_up(low_total / n) if n else 0.0,
        per_case_high=_round_up(high_total / n) if n else 0.0,
        calibrated=calibrated,
        tokenizer_method=method,
        input_exact=input_exact,
        output_ceiling=ceiling,
        ceiling_source=ceiling_source,
        input_tokens_total=input_tokens_total,
        output_tokens_low=output_tokens_low,
        output_tokens_high=output_tokens_high,
    )


def _cost_for_tokens(price, input_tokens: int, output_tokens: int) -> float:
    return price.cost(input_tokens, output_tokens)


def _estimate_blackbox_target(spec: TargetSpec, config: Config) -> TargetEstimate:
    """endpoint / command targets are black boxes — predict from the DECLARED
    cost basis only. NEVER tokenize a black box."""
    n = len(config.cases)
    per_req = spec.cost.amortized_per_request()
    if per_req is None:
        return TargetEstimate(
            target_id=spec.id,
            target_type=spec.type,
            n_cases=n,
            priced=False,
            cost_basis="estimated (no declared cost)",
            input_cost_total=None,
            output_cost_low=None,
            output_cost_high=None,
            per_case_low=None,
            per_case_high=None,
            note="declare a cost basis to estimate this target.",
        )
    total = _round_up(per_req * n)
    return TargetEstimate(
        target_id=spec.id,
        target_type=spec.type,
        n_cases=n,
        priced=True,
        cost_basis=f"estimated ({spec.cost.label})",
        # Declared per-request cost is not split into input/output.
        input_cost_total=None,
        output_cost_low=total,
        output_cost_high=total,
        per_case_low=_round_up(per_req),
        per_case_high=_round_up(per_req),
        note=spec.cost.assumption,
    )


def estimate_config(
    config: Config,
    pricing: PricingTable,
    limits: dict[str, dict],
    history: Optional[list[Observation]] = None,
    max_output_override: Optional[int] = None,
) -> list[TargetEstimate]:
    estimates: list[TargetEstimate] = []
    for spec in config.targets:
        if spec.type == "model" or spec.raw.get("token_priced", False):
            estimates.append(
                _estimate_model_target(
                    spec, config, pricing, limits, history, max_output_override
                )
            )
        else:
            estimates.append(_estimate_blackbox_target(spec, config))
    return estimates
