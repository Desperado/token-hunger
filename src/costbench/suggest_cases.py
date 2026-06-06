"""Suggest benchmark cases from a task prompt, using a cheap LLM.

This powers the UI's two-click flow: click *Suggest* to draft cases from the
current task, review them, then *Use* / *Regenerate* / *Discard*. It is a
convenience for authoring — the generated `expect` values are a starting point a
human confirms, never silently trusted. The model is picked from whatever
provider key is present (override with ``COSTBENCH_SUGGEST_MODEL``).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

# Provider key → a cheap, currently-valid model id to author cases with.
_SUGGEST_PREFERENCE = [
    ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
    ("DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
    ("MISTRAL_API_KEY", "mistral/mistral-small-latest"),
]

MAX_CASES = 24


def pick_model() -> Optional[str]:
    override = os.environ.get("COSTBENCH_SUGGEST_MODEL")
    if override:
        return override
    for env_var, model_id in _SUGGEST_PREFERENCE:
        if os.environ.get(env_var):
            return model_id
    return None


def _check_guidance(check: Any) -> str:
    kind = check.get("type") if isinstance(check, dict) else check
    if kind == "numeric":
        return ('The grader is NUMERIC: "expect" MUST be a bare number '
                '(integer or decimal), no units or words.')
    if kind == "contains":
        return ('The grader is CONTAINS: "expect" must be the exact substring the '
                'correct answer has to include (e.g. a label or the key word).')
    if kind == "regex":
        return ('The grader is REGEX: "expect" must be a regular expression the '
                'correct answer matches.')
    return ('The grader is EXACT: "expect" must be the full correct answer, '
            "matched case-insensitively after trimming whitespace.")


def _build_prompt(system: str, template: str, check: Any, n: int) -> str:
    return (
        "You are authoring evaluation test cases for the task below. Each case is "
        '{"input": <what fills the {input} placeholder>, "expect": <the correct '
        "ground-truth answer>}.\n\n"
        f"TASK SYSTEM PROMPT:\n{system or '(none)'}\n\n"
        f"PROMPT TEMPLATE: {template}\n\n"
        f"{_check_guidance(check)}\n\n"
        f"Produce exactly {n} DIVERSE, unambiguous cases with verifiable answers. "
        "Keep inputs short. Cover easy and hard examples, and balance the answer "
        "classes when the task is a classification.\n\n"
        "Return ONLY a JSON array of objects, no prose, no markdown fences. "
        'Example: [{"input": "...", "expect": "..."}]'
    )


def _parse_cases(text: str) -> list[dict]:
    """Pull the JSON array out of a model reply, tolerating stray prose/fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", cleaned).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("model did not return a JSON array of cases")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    cases = []
    for item in data:
        if not isinstance(item, dict) or "input" not in item or "expect" not in item:
            continue
        cases.append({"input": str(item["input"]), "expect": item["expect"]})
    if not cases:
        raise ValueError("no valid cases in the model's reply")
    return cases


def suggest_cases(task: dict, n: int = 10, model: Optional[str] = None) -> dict:
    """Draft ``n`` cases for ``task``. Returns ``{cases, model}``."""
    n = max(1, min(int(n), MAX_CASES))
    model = model or pick_model()
    if not model:
        raise RuntimeError(
            "no provider API key found to suggest cases — set one in .env "
            "(e.g. ANTHROPIC_API_KEY or GEMINI_API_KEY) or COSTBENCH_SUGGEST_MODEL"
        )
    try:
        import litellm
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "suggesting cases needs the optional dependency: pip install costbench[models]"
        ) from exc

    prompt = _build_prompt(
        task.get("system", ""),
        task.get("promptTemplate", "{input}"),
        task.get("check", "exact"),
        n,
    )
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    text = resp.choices[0].message.content or ""
    cases = _parse_cases(text)[:n]
    return {"cases": cases, "model": model}
