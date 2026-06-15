"""Bundled model catalog — single source of truth for pricing, limits, and priors.

All bundled model configuration lives in ``models.yaml``. ``pricing.load_pricing``,
``limits.load_model_limits``, and ``priors.load_priors`` delegate here by default.
A custom ``pricing_path`` in a run config may still point at a flat pricing-only
YAML file for private/negotiated rates.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml

from .pricing import PricingTable, _parse_entry, Price
from .priors import ModelPrior, Metric

BUNDLED_CATALOG = "models.yaml"


@dataclass(frozen=True)
class ModelCatalog:
    """In-memory view of the bundled (or custom) model catalog."""

    _entries: dict[str, dict]

    def ids(self) -> list[str]:
        return sorted(self._entries)

    def pricing_table(self) -> PricingTable:
        prices: dict[str, Price] = {}
        for mid, entry in self._entries.items():
            block = entry.get("pricing")
            if block:
                prices[mid] = _parse_entry(mid, block)
        return PricingTable(prices)

    def limits(self) -> dict[str, dict]:
        return {
            mid: dict(entry["limits"])
            for mid, entry in self._entries.items()
            if entry.get("limits")
        }

    def priors(self) -> dict[str, ModelPrior]:
        out: dict[str, ModelPrior] = {}
        for mid, entry in self._entries.items():
            block = entry.get("priors")
            if not block:
                continue
            metrics = [
                Metric(
                    name=m["name"],
                    value=float(m["value"]),
                    unit=m.get("unit", "percent"),
                    source=m.get("source", ""),
                    license=m.get("license", ""),
                    verified=str(m.get("verified", "")),
                )
                for m in (block.get("metrics") or [])
            ]
            out[mid] = ModelPrior(
                model_id=mid,
                task_strengths=list(block.get("task_strengths") or []),
                metrics=metrics,
                notes=block.get("notes", ""),
            )
        return out


def _read_catalog_text(path: Optional[str | Path] = None) -> str:
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    return resources.files("costbench").joinpath(BUNDLED_CATALOG).read_text(
        encoding="utf-8"
    )


def _parse_catalog_text(text: str) -> dict[str, dict]:
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{BUNDLED_CATALOG} root must be a mapping")
    return raw


def load_catalog(path: Optional[str | Path] = None) -> ModelCatalog:
    """Load the bundled model catalog, or a custom catalog YAML if given."""
    return ModelCatalog(_parse_catalog_text(_read_catalog_text(path)))


def is_flat_pricing_yaml(text: str) -> bool:
    """True when YAML looks like a legacy flat pricing table, not a catalog."""
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict) or not raw:
        return False
    sample = next(iter(raw.values()))
    if not isinstance(sample, dict):
        return False
    return "pricing" not in sample and (
        "input" in sample or sample.get("basis") == "amortized_gpu"
    )
