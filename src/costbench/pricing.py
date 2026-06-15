"""Transparent token pricing.

Prices come from the bundled model catalog (``models.yaml``), never from inside a
dependency. Callers can override or extend the table from their own config so a
private/negotiated rate or a brand-new model never blocks a run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml


@dataclass(frozen=True)
class ModelPrice:
    input_per_m: float  # USD per 1M prompt tokens
    output_per_m: float  # USD per 1M completion tokens
    verified: Optional[str] = None
    source: Optional[str] = None
    cost_basis_label: str = "$/token"

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.input_per_m
            + output_tokens / 1_000_000 * self.output_per_m
        )


@dataclass(frozen=True)
class AmortizedGpuPrice:
    """A local/self-hosted model priced by amortized GPU time, NOT a vendor
    $/token rate. Local infra does not bill input vs output separately, so cost
    is total tokens × a per-token rate derived from GPU $/hour and throughput.

    Carries a distinct ``cost_basis_label`` so the report never blends this
    silently with vendor $/token numbers. batch-size-1 throughput defaults are
    over-estimate-safe; override per hardware."""

    gpu_hourly_rate: float          # USD per GPU-hour
    throughput_tokens_per_sec: float
    verified: Optional[str] = None
    source: Optional[str] = None
    note: Optional[str] = None
    cost_basis_label: str = "amortized GPU (batch 1)"

    @property
    def per_token(self) -> float:
        return self.gpu_hourly_rate / self.throughput_tokens_per_sec / 3600.0

    # Exposed in $/1M for the suggest blended-price proxy and `models` listing.
    @property
    def input_per_m(self) -> float:
        return self.per_token * 1_000_000

    @property
    def output_per_m(self) -> float:
        return self.per_token * 1_000_000

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens + output_tokens) * self.per_token

    def with_infra(
        self,
        gpu_hourly_rate: Optional[float] = None,
        throughput_tokens_per_sec: Optional[float] = None,
    ) -> "AmortizedGpuPrice":
        """Return a copy with per-target infra overrides applied."""
        from dataclasses import replace

        changes = {}
        if gpu_hourly_rate is not None:
            changes["gpu_hourly_rate"] = gpu_hourly_rate
        if throughput_tokens_per_sec is not None:
            changes["throughput_tokens_per_sec"] = throughput_tokens_per_sec
        return replace(self, **changes) if changes else self


Price = Union[ModelPrice, AmortizedGpuPrice]


class PricingTable:
    def __init__(self, prices: dict[str, Price]):
        self._prices = prices
        canonical = {
            model_id: (
                {
                    "basis": "amortized_gpu",
                    "gpu_hourly_rate": price.gpu_hourly_rate,
                    "throughput_tokens_per_sec": price.throughput_tokens_per_sec,
                    "verified": str(price.verified or ""),
                    "source": price.source or "",
                }
                if isinstance(price, AmortizedGpuPrice)
                else {
                    "input": price.input_per_m,
                    "output": price.output_per_m,
                    "verified": str(price.verified or ""),
                    "source": price.source or "",
                }
            )
            for model_id, price in sorted(prices.items())
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        self.fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]

    def get(self, model_id: str) -> Optional[Price]:
        return self._prices.get(model_id)

    def __contains__(self, model_id: str) -> bool:
        return model_id in self._prices

    def ids(self) -> list[str]:
        return sorted(self._prices)

    def with_overrides(self, overrides: dict[str, dict]) -> "PricingTable":
        merged = dict(self._prices)
        for model_id, entry in (overrides or {}).items():
            merged[model_id] = _parse_entry(model_id, entry)
        return PricingTable(merged)


def _parse_entry(model_id: str, entry: dict) -> Price:
    if isinstance(entry, dict) and entry.get("basis") == "amortized_gpu":
        try:
            rate = float(entry["gpu_hourly_rate"])
            tput = float(entry["throughput_tokens_per_sec"])
            if rate <= 0 or tput <= 0:
                raise ValueError("gpu_hourly_rate and throughput_tokens_per_sec must be > 0")
            return AmortizedGpuPrice(
                gpu_hourly_rate=rate,
                throughput_tokens_per_sec=tput,
                verified=entry.get("verified"),
                source=entry.get("source"),
                note=entry.get("note"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"bad amortized_gpu pricing entry for {model_id!r}: {entry!r}"
            ) from exc
    try:
        return ModelPrice(
            input_per_m=float(entry["input"]),
            output_per_m=float(entry["output"]),
            verified=entry.get("verified"),
            source=entry.get("source"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"bad pricing entry for {model_id!r}: {entry!r}") from exc


def _load_yaml_text(text: str) -> dict[str, Price]:
    raw = yaml.safe_load(text) or {}
    return {mid: _parse_entry(mid, entry) for mid, entry in raw.items()}


def load_pricing(path: Optional[str | Path] = None) -> PricingTable:
    """Load pricing from the bundled catalog, or a custom YAML file if given.

    A custom path may be a full ``models.yaml`` catalog or a legacy flat
    pricing-only table (``input``/``output`` per model id).
    """
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
        from .models import is_flat_pricing_yaml, load_catalog

        if is_flat_pricing_yaml(text):
            return PricingTable(_load_yaml_text(text))
        return load_catalog(path).pricing_table()
    from .models import load_catalog

    return load_catalog().pricing_table()
