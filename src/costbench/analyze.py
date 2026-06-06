"""Opt-in LLM analysis for suggestion bootstrapping.

The analyzer sends task instructions and a bounded sample of case inputs to a
user-selected LiteLLM model. Expected answers, target definitions, credentials,
and pricing are deliberately excluded.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from .config import Config

if TYPE_CHECKING:
    from .pricing import PricingTable

TASK_TYPES = {"coding", "math", "general"}
CATEGORIES = {
    "classification",
    "extraction",
    "summarization",
    "generation",
    "reasoning",
    "coding",
    "math",
    "other",
}
COMPLEXITIES = {"low", "medium", "high"}
MAX_CASES = 5
MAX_CASE_CHARS = 1000
MAX_SYSTEM_CHARS = 4000
MAX_TEMPLATE_CHARS = 2000

_SYSTEM_PROMPT = """You classify an LLM benchmark before model selection.
Return one JSON object only, with this exact shape:
{
  "task_type": "coding|math|general",
  "category":
    "classification|extraction|summarization|generation|reasoning|coding|math|other",
  "complexity": "low|medium|high",
  "confidence": 0.0,
  "reason": "brief explanation",
  "signals": ["brief signal"]
}

Use task_type only as the broad benchmark-prior family:
- coding: generating, reviewing, debugging, or transforming code
- math: calculation, formal math, or quantitative problem solving
- general: all other workloads

Judge complexity from reasoning depth, instruction constraints, input
variability, output structure, and domain knowledge. Do not solve the cases.
Do not include markdown or any text outside the JSON object."""


@dataclass(frozen=True)
class TaskAnalysis:
    task_type: str
    category: str
    complexity: str
    confidence: float
    reason: str
    signals: tuple[str, ...]
    analyzer_model: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost: Optional[float] = None
    cost_basis: str = "unknown"


def _analysis_payload(config: Config) -> dict[str, Any]:
    return {
        "benchmark_name": config.name,
        "system": (config.task.system or "")[:MAX_SYSTEM_CHARS],
        "prompt_template": config.task.prompt_template[:MAX_TEMPLATE_CHARS],
        "check": config.check,
        "case_inputs": [
            case.input[:MAX_CASE_CHARS] for case in config.cases[:MAX_CASES]
        ],
    }


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("analyzer returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("analyzer response must be a JSON object")
    return value


def _parse_analysis(
    raw: dict[str, Any],
    analyzer_model: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost: Optional[float] = None,
    cost_basis: str = "unknown",
) -> TaskAnalysis:
    task_type = str(raw.get("task_type", "")).lower()
    category = str(raw.get("category", "")).lower()
    complexity = str(raw.get("complexity", "")).lower()
    if task_type not in TASK_TYPES:
        raise ValueError(
            "analyzer task_type must be coding, math, or general"
        )
    if category not in CATEGORIES:
        raise ValueError(f"analyzer returned unknown category {category!r}")
    if complexity not in COMPLEXITIES:
        raise ValueError("analyzer complexity must be low, medium, or high")
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError("analyzer confidence must be between 0 and 1") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("analyzer confidence must be between 0 and 1")

    reason = str(raw.get("reason", "")).strip()
    if not reason:
        raise ValueError("analyzer response needs a reason")
    signals_raw = raw.get("signals", [])
    if not isinstance(signals_raw, list):
        raise ValueError("analyzer signals must be a list")
    signals = tuple(
        str(signal).strip()
        for signal in signals_raw[:5]
        if str(signal).strip()
    )

    return TaskAnalysis(
        task_type=task_type,
        category=category,
        complexity=complexity,
        confidence=confidence,
        reason=reason[:500],
        signals=signals,
        analyzer_model=analyzer_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        cost_basis=cost_basis,
    )


def _usage_value(usage: Any, name: str) -> Optional[int]:
    value = (
        usage.get(name)
        if isinstance(usage, dict)
        else getattr(usage, name, None)
    )
    return int(value) if value is not None else None


def analyze_config(
    config: Config,
    analyzer_model: str,
    pricing: Optional["PricingTable"] = None,
) -> TaskAnalysis:
    """Classify a benchmark using a user-selected LiteLLM model."""
    analyzer_model = analyzer_model.strip()
    if not analyzer_model:
        raise ValueError("analyzer model cannot be empty")
    try:
        import litellm
    except ModuleNotFoundError as exc:
        raise ValueError(
            "LLM analysis needs the optional dependency: "
            "pip install costbench[models]"
        ) from exc

    payload = json.dumps(
        _analysis_payload(config),
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        response = litellm.completion(
            model=analyzer_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            temperature=0,
            max_tokens=300,
        )
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        input_tokens = _usage_value(usage, "prompt_tokens") if usage else None
        output_tokens = _usage_value(usage, "completion_tokens") if usage else None
    except Exception as exc:  # noqa: BLE001 - normalize provider failures for CLI
        raise ValueError(
            f"task analysis failed via {analyzer_model!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    cost = None
    cost_basis = "unknown"
    price = pricing.get(analyzer_model) if pricing is not None else None
    if price and input_tokens is not None and output_tokens is not None:
        cost = price.cost(input_tokens, output_tokens)
        cost_basis = price.cost_basis_label
    return _parse_analysis(
        _json_object(str(content)),
        analyzer_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        cost_basis=cost_basis,
    )


def render_analysis_terminal(analysis: TaskAnalysis, console) -> None:
    console.print(
        "[bold]Task analysis[/bold]: "
        f"type [cyan]{analysis.task_type}[/cyan], "
        f"category [cyan]{analysis.category}[/cyan], "
        f"complexity [cyan]{analysis.complexity}[/cyan], "
        f"confidence {analysis.confidence:.0%}"
    )
    console.print(f"[dim]{analysis.reason}[/dim]")
    if analysis.signals:
        console.print(f"[dim]Signals: {', '.join(analysis.signals)}[/dim]")
    if analysis.cost is not None:
        console.print(
            f"[dim]Analyzer call: {analysis.input_tokens} input + "
            f"{analysis.output_tokens} output tokens; "
            f"${analysis.cost:.6f} ({analysis.cost_basis}).[/dim]"
        )
    else:
        console.print(
            "[dim]Analyzer call cost unknown: token usage or a matching pricing "
            "entry was unavailable.[/dim]"
        )
    console.print(
        "[dim]Complexity is informational in the MVP; ranking uses the detected "
        "task type plus static priors. Validate recommendations with "
        "`costbench run`.[/dim]\n"
    )
