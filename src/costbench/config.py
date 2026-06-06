"""Config loading and validation.

A run is fully described by one YAML file: the targets to compare, the task,
the correctness check, and the cases. Everything is declarative so adding a
target or a competitor is editing YAML, not writing code.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class CostSpec:
    """How to cost a non-model target whose tokens we can't see.

    basis is one of: 'per_request', 'subscription', 'per_second', 'unknown'.
    We never silently blend these with per-token costs in one number.

    'per_second' is the sandbox basis: cost is *measured* from runtime, so
    :meth:`amortized_per_request` can't know it up front and the executing
    target multiplies the rate by observed seconds via :meth:`cost_for_seconds`.
    """

    basis: str = "unknown"
    per_request: Optional[float] = None
    monthly: Optional[float] = None
    expected_monthly_volume: Optional[int] = None
    per_second: Optional[float] = None
    note: Optional[str] = None

    def amortized_per_request(self) -> Optional[float]:
        if self.basis == "per_request":
            return self.per_request
        if (
            self.basis == "subscription"
            and self.monthly is not None
            and self.expected_monthly_volume
        ):
            return self.monthly / self.expected_monthly_volume
        return None

    def cost_for_seconds(self, seconds: float) -> Optional[float]:
        """Measured cost for a runtime-billed target (e.g. an e2b sandbox)."""
        if self.basis == "per_second" and self.per_second is not None:
            return self.per_second * seconds
        return None

    @property
    def label(self) -> str:
        return {
            "per_request": "per-request",
            "subscription": "subscription-amortized",
            "per_second": "measured-runtime-seconds",
            "unknown": "unknown",
        }.get(self.basis, self.basis)

    @property
    def assumption(self) -> Optional[str]:
        if self.note:
            return self.note
        if (
            self.basis == "subscription"
            and self.monthly is not None
            and self.expected_monthly_volume
        ):
            return (
                f"${self.monthly:g}/month over "
                f"{self.expected_monthly_volume:,} expected requests"
            )
        return None


@dataclass
class InfraCost:
    """Per-target override for an amortized-GPU (local/self-hosted) model.

    A clean hook for the user's declared infra cost: their own GPU $/hour and
    serving throughput override the pricing-table defaults at cost time."""

    gpu_hourly_rate: Optional[float] = None
    throughput_tokens_per_sec: Optional[float] = None


@dataclass
class TargetSpec:
    type: str  # model | endpoint | command
    id: str
    raw: dict[str, Any] = field(default_factory=dict)
    cost: CostSpec = field(default_factory=CostSpec)
    infra_cost: Optional[InfraCost] = None


@dataclass
class Case:
    input: str
    expect: Any
    check: Optional[Any] = None  # optional per-case check override


@dataclass
class TaskSpec:
    system: Optional[str] = None
    prompt_template: str = "{input}"


@dataclass
class Config:
    name: str
    targets: list[TargetSpec]
    task: TaskSpec
    check: Any
    cases: list[Case]
    pricing_overrides: dict[str, dict] = field(default_factory=dict)
    pricing_path: Optional[str] = None
    source_path: Optional[str] = None
    fingerprint: str = ""


def _parse_cost(raw: Optional[dict]) -> CostSpec:
    if not raw:
        return CostSpec()
    if not isinstance(raw, dict):
        raise ValueError(f"target cost must be a mapping, got {raw!r}")
    try:
        cost = CostSpec(
            basis=raw.get("basis", "unknown"),
            per_request=(
                float(raw["per_request"]) if raw.get("per_request") is not None else None
            ),
            monthly=float(raw["monthly"]) if raw.get("monthly") is not None else None,
            expected_monthly_volume=(
                int(raw["expected_monthly_volume"])
                if raw.get("expected_monthly_volume") is not None
                else None
            ),
            per_second=(
                float(raw["per_second"]) if raw.get("per_second") is not None else None
            ),
            note=raw.get("note"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value in target cost: {raw!r}") from exc
    if cost.basis not in ("per_request", "subscription", "per_second", "unknown"):
        raise ValueError(
            f"unknown cost basis {cost.basis!r}; "
            "use per_request, subscription, per_second, or unknown"
        )
    if cost.basis == "per_request":
        if cost.per_request is None or cost.per_request < 0:
            raise ValueError("per_request cost needs a non-negative 'per_request'")
    if cost.basis == "subscription":
        if cost.monthly is None or cost.monthly < 0:
            raise ValueError("subscription cost needs a non-negative 'monthly'")
        if not cost.expected_monthly_volume or cost.expected_monthly_volume < 1:
            raise ValueError(
                "subscription cost needs a positive 'expected_monthly_volume'"
            )
    if cost.basis == "per_second":
        if cost.per_second is None or cost.per_second < 0:
            raise ValueError("per_second cost needs a non-negative 'per_second'")
    return cost


def _parse_target(raw: dict) -> TargetSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"target must be a mapping, got {raw!r}")
    if "type" not in raw:
        raise ValueError(f"target missing 'type': {raw!r}")
    ttype = raw["type"]
    if ttype not in ("model", "endpoint", "command"):
        raise ValueError(
            f"unknown target type {ttype!r}; use model, endpoint, or command"
        )
    tid = raw.get("id") or raw.get("url") or raw.get("command")
    if not tid:
        raise ValueError(f"target missing 'id': {raw!r}")
    if ttype == "endpoint" and not raw.get("url"):
        raise ValueError(f"endpoint target missing 'url': {raw!r}")
    if ttype == "command" and not raw.get("command"):
        raise ValueError(f"command target missing 'command': {raw!r}")
    cost = _parse_cost(raw.get("cost"))
    sandbox = raw.get("sandbox")
    if sandbox is not None:
        if ttype != "command":
            raise ValueError(f"'sandbox' only applies to command targets: {raw!r}")
        if sandbox not in ("local", "e2b"):
            raise ValueError(
                f"unknown sandbox {sandbox!r}; use local or e2b"
            )
    if sandbox == "e2b":
        if cost.basis != "per_second" or cost.per_second is None:
            raise ValueError(
                "e2b command targets require "
                "cost: {basis: per_second, per_second: <combined rate>}"
            )
        try:
            create_interval = float(raw.get("sandbox_create_interval", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "sandbox_create_interval must be a non-negative number"
            ) from exc
        if not math.isfinite(create_interval) or create_interval < 0:
            raise ValueError(
                "sandbox_create_interval must be a finite non-negative number"
            )
    elif cost.basis == "per_second":
        raise ValueError(
            "per_second cost only applies to command targets with sandbox: e2b"
        )
    return TargetSpec(
        type=ttype,
        id=str(tid) if not isinstance(tid, str) else tid,
        raw=raw,
        cost=cost,
        infra_cost=_parse_infra_cost(raw.get("infra_cost")),
    )


def _parse_infra_cost(raw: Optional[dict]) -> Optional[InfraCost]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"target infra_cost must be a mapping, got {raw!r}")
    try:
        rate = (
            float(raw["gpu_hourly_rate"])
            if raw.get("gpu_hourly_rate") is not None
            else None
        )
        tput = (
            float(raw["throughput_tokens_per_sec"])
            if raw.get("throughput_tokens_per_sec") is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value in infra_cost: {raw!r}") from exc
    if rate is not None and rate <= 0:
        raise ValueError("infra_cost gpu_hourly_rate must be > 0")
    if tput is not None and tput <= 0:
        raise ValueError("infra_cost throughput_tokens_per_sec must be > 0")
    return InfraCost(gpu_hourly_rate=rate, throughput_tokens_per_sec=tput)


def build_config(
    raw: dict,
    *,
    base_dir: Path,
    source_path: Optional[str] = None,
    default_name: str = "costbench",
    fingerprint_text: Optional[str] = None,
) -> Config:
    """Build a :class:`Config` from an already-parsed mapping.

    This is the shared core of :func:`load_config`; it also lets in-process
    callers (the server) build a config from posted JSON without writing a file.
    ``base_dir`` resolves a ``file`` case source; ``fingerprint_text`` is the
    exact bytes to fingerprint (the YAML text for a file, a canonical JSON dump
    for an in-memory config) so the fingerprint stays stable per input.
    """
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")

    if not isinstance(raw.get("targets"), list) or not raw["targets"]:
        raise ValueError("config needs a non-empty 'targets' list")
    # 'cases' may be an inline list (original form) or a {source: ...} mapping
    # resolved by the sources module; either way it must be present.
    if not raw.get("cases"):
        raise ValueError("config needs 'cases' (an inline list or a {source: ...} mapping)")

    task_raw = raw.get("task") or {}
    if not isinstance(task_raw, dict):
        raise ValueError("config 'task' must be a mapping")
    task = TaskSpec(
        system=task_raw.get("system"),
        prompt_template=task_raw.get("prompt_template", "{input}"),
    )

    # Lazy import avoids a circular dependency: sources imports Case from here.
    from .sources import load_cases

    cases, content_key = load_cases(raw["cases"], base_dir=base_dir)

    # Fingerprint the exact input bytes; for an in-memory config fall back to a
    # canonical JSON dump so the same posted config always fingerprints alike.
    if fingerprint_text is None:
        fingerprint_text = json.dumps(raw, sort_keys=True, default=str)
    # Fold the resolved-case content in so a file-sourced run is pinned to the
    # bytes it actually scored, not just the config text.
    fp_material = (
        fingerprint_text
        if not content_key
        else f"{fingerprint_text}\ncases-content:{content_key}"
    )

    return Config(
        name=raw.get("name", default_name),
        targets=[_parse_target(t) for t in raw["targets"]],
        task=task,
        check=raw.get("check", "exact"),
        cases=cases,
        pricing_overrides=raw.get("pricing", {}) or {},
        pricing_path=raw.get("pricing_path"),
        source_path=source_path,
        fingerprint=hashlib.sha256(fp_material.encode("utf-8")).hexdigest()[:12],
    )


def load_config(path: str | Path) -> Config:
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return build_config(
        raw,
        base_dir=Path(path).resolve().parent,
        source_path=str(path),
        default_name=Path(path).stem,
        fingerprint_text=text,
    )
