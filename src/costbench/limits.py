"""Model output/context limits, loaded from a committed YAML table.

Mirrors ``pricing.load_pricing``: the worst-case output ceiling lives in plain
text in the repo, with a verified date + source per entry, so the number
costbench uses to bound output cost is auditable. Unknown models fall back to a
research-recommended safe default of 4096 output tokens.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_MAX_OUTPUT_TOKENS = 4096


def load_model_limits(path: Optional[str | Path] = None) -> dict[str, dict]:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("costbench").joinpath("model_limits.yaml").read_text(
            encoding="utf-8"
        )
    raw = yaml.safe_load(text) or {}
    if not isinstance(raw, dict):
        raise ValueError("model_limits.yaml root must be a mapping")
    return raw
