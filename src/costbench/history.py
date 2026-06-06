"""Calibration history — a plain local file costbench owns.

Records observed token usage per (config fingerprint, target) from real `run`
invocations, so a later `estimate` can show real p50/p90 instead of only the
worst-case ceiling. Stored as JSON Lines (append-only) so concurrent runs append
safely and a future host can stream-read it.

Best-effort by design: a failure to write history must NEVER fail a run.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Don't show a "calibrated" range off 1-2 points — that would be fake precision.
MIN_SAMPLES = 5

DEFAULT_HISTORY = "~/.costbench/history.jsonl"


@dataclass(frozen=True)
class Observation:
    config_fingerprint: str
    target_id: str
    model_id: str
    input_tokens: int
    output_tokens: int
    cost: Optional[float]
    passed: bool
    ts: str
    pricing_fingerprint: str = ""
    observation_id: str = ""
    source: str = "run"
    schema_version: int = 1


@dataclass(frozen=True)
class TokenPercentiles:
    n: int
    input_p50: int
    input_p90: int
    output_p50: int
    output_p90: int


def history_path() -> Path:
    raw = os.environ.get("COSTBENCH_HISTORY", DEFAULT_HISTORY)
    return Path(raw).expanduser()


def append_observations(obs: list[Observation], path: Optional[str | Path] = None) -> None:
    if not obs:
        return
    p = Path(path).expanduser() if path is not None else history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        for o in obs:
            fh.write(json.dumps(asdict(o), separators=(",", ":")) + "\n")


def append_unique_observations(
    obs: list[Observation], path: Optional[str | Path] = None
) -> int:
    """Append observations, skipping imported rows already present by stable ID."""
    if not obs:
        return 0
    existing_ids = {
        o.observation_id
        for o in load_observations(path)
        if o.observation_id
    }
    unique: list[Observation] = []
    seen = set(existing_ids)
    for observation in obs:
        if observation.observation_id and observation.observation_id in seen:
            continue
        unique.append(observation)
        if observation.observation_id:
            seen.add(observation.observation_id)
    append_observations(unique, path)
    return len(unique)


def load_observations(path: Optional[str | Path] = None) -> list[Observation]:
    """Load all observations, tolerating malformed lines (skip and continue)."""
    p = Path(path).expanduser() if path is not None else history_path()
    if not p.exists():
        return []
    out: list[Observation] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            out.append(
                Observation(
                    config_fingerprint=d["config_fingerprint"],
                    target_id=d["target_id"],
                    model_id=d.get("model_id", d["target_id"]),
                    input_tokens=int(d["input_tokens"]),
                    output_tokens=int(d["output_tokens"]),
                    cost=d.get("cost"),
                    passed=bool(d.get("passed", False)),
                    ts=d.get("ts", ""),
                    pricing_fingerprint=d.get("pricing_fingerprint", ""),
                    observation_id=d.get("observation_id", ""),
                    source=d.get("source", "run"),
                    schema_version=int(d.get("schema_version", 1)),
                )
            )
        except (ValueError, KeyError, TypeError):
            # Malformed line — skip, never crash a read.
            continue
    return out


def _nearest_rank(sorted_vals: list[int], pct: float) -> int:
    """Nearest-rank percentile, rounding the rank UP (over-estimate-safe)."""
    if not sorted_vals:
        return 0
    rank = math.ceil(pct / 100.0 * len(sorted_vals))
    rank = max(1, min(rank, len(sorted_vals)))
    return sorted_vals[rank - 1]


def percentiles_for(
    obs: list[Observation], config_fingerprint: str, target_id: str
) -> Optional[TokenPercentiles]:
    """p50/p90 token usage for one (config, target). None if < MIN_SAMPLES.

    p90 rounds UP (feeds the HIGH end of the estimate range — over-estimate-safe)."""
    matched = [
        o
        for o in obs
        if o.config_fingerprint == config_fingerprint and o.target_id == target_id
    ]
    if len(matched) < MIN_SAMPLES:
        return None
    ins = sorted(o.input_tokens for o in matched)
    outs = sorted(o.output_tokens for o in matched)
    return TokenPercentiles(
        n=len(matched),
        input_p50=_nearest_rank(ins, 50),
        input_p90=_nearest_rank(ins, 90),
        output_p50=_nearest_rank(outs, 50),
        output_p90=_nearest_rank(outs, 90),
    )
