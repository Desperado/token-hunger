"""LLM-as-judge check for the *secondary* QualityMax semantic benchmark.

Read this before trusting the number it produces:

costbench keeps LLM-as-judge OUT of its core checks on purpose — the moment a
benchmark's "success" depends on a model's opinion, the result becomes arguable,
and arguable is the one thing a benchmark cannot be (see
``src/costbench/checks.py``). So this judge ships as an opt-in ``code`` check,
clearly labeled as a diagnostic companion to the deterministic label benchmark
(``label.yaml``), never the headline cost-per-success metric.

A ``code`` check is any callable ``(output, expect) -> bool | (bool, str)``.
Here ``output`` is the target's answer and ``expect`` is the human-written
``expected_results`` text. The judge model and its cost are NOT counted in the
benchmark's cost — only the target's cost is. Keep that asymmetry in mind.
"""

from __future__ import annotations

import os

# Use a small, cheap, fixed judge so the verdict is as stable/comparable as an
# arguable verdict can be. Override via COSTBENCH_JUDGE_MODEL if you must.
JUDGE_MODEL = os.environ.get("COSTBENCH_JUDGE_MODEL", "anthropic/claude-haiku-4-5")

_PROMPT = """You are grading whether a candidate answer satisfies an expected \
result for a software test case. Be strict but fair: the candidate need not match \
word-for-word, but it must capture the same expected outcome.

EXPECTED RESULT:
{expect}

CANDIDATE ANSWER:
{output}

Reply with exactly one word on the first line: PASS or FAIL. Optionally add a \
short reason on the next line."""


def grade(output: str, expect) -> tuple[bool, str]:
    try:
        import litellm
    except ModuleNotFoundError:
        return False, "judge needs litellm: pip install costbench[models]"

    prompt = _PROMPT.format(expect=str(expect), output=str(output))
    try:
        resp = litellm.completion(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 — a judge failure must not crash the run
        return False, f"judge error: {type(exc).__name__}: {exc}"

    verdict = (resp.choices[0].message.content or "").strip()
    passed = verdict.upper().startswith("PASS")
    return passed, verdict[:200]
