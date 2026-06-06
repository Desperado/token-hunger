"""Transparent token pricing.

Prices come from a committed YAML table (``pricing.yaml``), never from inside a
dependency. Callers can override or extend the table from their own config so a
private/negotiated rate or a brand-new model never blocks a run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class ModelPrice:
    input_per_m: float  # USD per 1M prompt tokens
    output_per_m: float  # USD per 1M completion tokens
    verified: Optional[str] = None
    source: Optional[str] = None

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.input_per_m
            + output_tokens / 1_000_000 * self.output_per_m
        )


class PricingTable:
    def __init__(self, prices: dict[str, ModelPrice]):
        self._prices = prices
        canonical = {
            model_id: {
                "input": price.input_per_m,
                "output": price.output_per_m,
                "verified": str(price.verified or ""),
                "source": price.source or "",
            }
            for model_id, price in sorted(prices.items())
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        self.fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]

    def get(self, model_id: str) -> Optional[ModelPrice]:
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


def _parse_entry(model_id: str, entry: dict) -> ModelPrice:
    try:
        return ModelPrice(
            input_per_m=float(entry["input"]),
            output_per_m=float(entry["output"]),
            verified=entry.get("verified"),
            source=entry.get("source"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"bad pricing entry for {model_id!r}: {entry!r}") from exc


def _load_yaml_text(text: str) -> dict[str, ModelPrice]:
    raw = yaml.safe_load(text) or {}
    return {mid: _parse_entry(mid, entry) for mid, entry in raw.items()}


def load_pricing(path: Optional[str | Path] = None) -> PricingTable:
    """Load the built-in pricing table, or a custom YAML file if given."""
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("costbench").joinpath("pricing.yaml").read_text(
            encoding="utf-8"
        )
    return PricingTable(_load_yaml_text(text))
