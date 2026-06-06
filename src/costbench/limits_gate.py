"""Free-tier seam for `estimate` — a HOOK, not billing.

v1 always allows. This is the seam a future host overrides/monkeypatches or
swaps via env var to enforce a free-tier limit on heavier/continuous use. No
billing, no counting persisted today. Default (env unset) => unlimited =>
OSS behavior unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: str = ""


# None => unlimited (OSS default). A host sets the env var or replaces this fn.
FREE_TIER_MAX_CASES = int(os.environ.get("COSTBENCH_FREE_TIER_MAX_CASES", "0")) or None


def check_estimate_quota(config) -> QuotaDecision:
    if FREE_TIER_MAX_CASES and len(config.cases) > FREE_TIER_MAX_CASES:
        return QuotaDecision(
            False,
            f"estimate is limited to {FREE_TIER_MAX_CASES} cases on the free tier; "
            f"this config has {len(config.cases)}.",
        )
    return QuotaDecision(True)
