"""Model output/context limits, loaded from the bundled model catalog.

Mirrors ``pricing.load_pricing``: the worst-case output ceiling lives in plain
text in the repo, with a verified date + source per entry, so the number
costbench uses to bound output cost is auditable. Unknown models fall back to a
research-recommended safe default of 4096 output tokens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from .models import BUNDLED_CATALOG, load_catalog

DEFAULT_MAX_OUTPUT_TOKENS = 4096


def load_model_limits(path: Optional[str | Path] = None) -> dict[str, dict]:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
        raw = yaml.safe_load(text) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path} root must be a mapping")
        sample = next(iter(raw.values()), None) if raw else None
        if isinstance(sample, dict) and "limits" in sample:
            return load_catalog(path).limits()
        return raw
    return load_catalog().limits()
