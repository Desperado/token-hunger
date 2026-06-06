#!/usr/bin/env python3
"""A tiny, dependency-free stand-in 'classifier' used by the offline demo.

It is NOT a model — it's a keyword heuristic, so the offline demo runs with no
API keys and no cost. Two modes with different accuracy let the demo show the
cost-per-success inversion (the cheaper-per-call target isn't the cheaper one
per correct answer). Reads the ticket on stdin, prints ESCALATE or RESOLVE.
"""

import json
import sys

STRONG = ("fraud", "sue", "lawyer", "data leak", "deleted", "down", "outage",
          "breach", "gdpr", "admin access", "pii", "security", "charged twice",
          "never made", "logged into my account", "losing customers", "broke our")
WEAK = ("scam", "cancel", "unacceptable", "critical")


def classify(text: str, mode: str) -> str:
    t = text.lower()
    if any(k in t for k in STRONG):
        return "ESCALATE"
    if mode == "smart" and any(k in t for k in WEAK):
        return "ESCALATE"
    return "RESOLVE"


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "naive"
    raw = sys.stdin.read()
    try:
        text = json.loads(raw).get("input", raw)
    except (json.JSONDecodeError, AttributeError):
        text = raw
    print(classify(text, mode))


if __name__ == "__main__":
    main()
