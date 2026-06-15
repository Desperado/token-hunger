"""Model quality priors for `costbench suggest <task-type>`.

Priors are PUBLIC-benchmark starting points, NOT ground truth. The only ground
truth is the user's own `costbench run` on their real cases. The seed dataset
in the bundled model catalog (``models.yaml``) ships only openly-licensed
benchmarks + provider system-card numbers, each with a source + license +
verified date.

Artificial Analysis is OPT-IN at runtime only (user's own API key, nothing
cached to disk). The seed source is the default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Protocol

from .pricing import PricingTable

STALE_DAYS = 30


@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    unit: str
    source: str
    license: str
    verified: str


@dataclass(frozen=True)
class ModelPrior:
    model_id: str
    task_strengths: list[str] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    notes: str = ""

    def _relevant(self, task_type: str) -> list[Metric]:
        # Prefer the benchmark that actually measures this task (e.g. HumanEval
        # for coding) so a coding rank is not diluted by a general-knowledge
        # score like MMLU. Only if no task-specific benchmark exists do we fall
        # back to the model's declared strengths. Deterministic.
        hint = {"coding": "humaneval", "math": "math", "general": "mmlu"}.get(task_type)
        if hint:
            hinted = [m for m in self.metrics if hint in m.name.lower()]
            if hinted:
                return hinted
        if task_type in self.task_strengths:
            return list(self.metrics)
        return []

    def quality_score(self, task_type: str) -> Optional[float]:
        """Mean of task-relevant metrics, normalized to 0–1. None if none."""
        rel = [m for m in self._relevant(task_type) if m.unit == "percent"]
        if not rel:
            return None
        return sum(m.value for m in rel) / len(rel) / 100.0


# --- sources ----------------------------------------------------------------


class ModelQualitySource(Protocol):
    def fetch_scores(self, model_ids: list[str]) -> dict[str, ModelPrior]: ...


class SeedSource:
    """Reads priors from the bundled model catalog (default source)."""

    def __init__(self, path: Optional[str | Path] = None):
        self._path = path

    def _load_all(self) -> dict[str, ModelPrior]:
        from .models import load_catalog

        return load_catalog(self._path).priors()

    def fetch_scores(self, model_ids: list[str]) -> dict[str, ModelPrior]:
        allp = self._load_all()
        if not model_ids:
            return allp
        return {mid: allp[mid] for mid in model_ids if mid in allp}


class ArtificialAnalysisSource:
    """Opt-in only. Requires the USER's own key; caches nothing to disk.

    Runtime fetch is a roadmap item — not bundled, not implemented."""

    def fetch_scores(self, model_ids: list[str]) -> dict[str, ModelPrior]:
        raise NotImplementedError(
            "opt-in AA source: provide ARTIFICIAL_ANALYSIS_API_KEY; runtime "
            "fetch is a roadmap item. Artificial Analysis data is not bundled."
        )


def load_priors(source: str = "seed") -> dict[str, ModelPrior]:
    if source == "seed":
        return SeedSource().fetch_scores([])
    if source == "artificialanalysis":
        return ArtificialAnalysisSource().fetch_scores([])
    raise ValueError(f"unknown priors source {source!r}")


# --- ranking ----------------------------------------------------------------


@dataclass(frozen=True)
class Suggestion:
    model_id: str
    quality: float
    blended_per_m: float
    quality_per_dollar: float
    sources: list[str]
    price_stale: bool


def _blended_per_m(price) -> Optional[float]:
    """Blended $/1M assuming a 3:1 input:output ratio (documented assumption)."""
    if price is None:
        return None
    return (3 * price.input_per_m + 1 * price.output_per_m) / 4


def _is_stale(verified: Optional[str]) -> bool:
    if not verified:
        return True
    try:
        d = datetime.strptime(str(verified), "%Y-%m-%d").date()
    except ValueError:
        return True
    return (date.today() - d).days > STALE_DAYS


def rank_models(
    task_type: str,
    priors: dict[str, ModelPrior],
    pricing: PricingTable,
    top: int = 5,
) -> tuple[list[Suggestion], list[ModelPrior]]:
    """Rank priced models with priors by quality-per-dollar. Returns
    (ranked suggestions, models with no priors for this task)."""
    ranked: list[Suggestion] = []
    unranked: list[ModelPrior] = []
    for mid, prior in priors.items():
        price = pricing.get(mid)
        quality = prior.quality_score(task_type)
        blended = _blended_per_m(price)
        if quality is None or blended is None or blended <= 0:
            unranked.append(prior)
            continue
        ranked.append(
            Suggestion(
                model_id=mid,
                quality=quality,
                blended_per_m=blended,
                quality_per_dollar=quality / blended,
                sources=sorted({m.source for m in prior.metrics if m.source}),
                price_stale=_is_stale(getattr(price, "verified", None)),
            )
        )
    ranked.sort(key=lambda s: s.quality_per_dollar, reverse=True)
    return ranked[:top], unranked


def render_suggest_terminal(task_type, ranked, unranked, console=None) -> None:
    from rich.console import Console
    from rich.table import Table

    console = console or Console()
    table = Table(title=f"costbench suggest — {task_type}", title_style="bold")
    table.add_column("Model", style="bold")
    table.add_column("Task quality", justify="right")
    table.add_column("Blended $/1M", justify="right")
    table.add_column("Quality-per-$", justify="right", style="bold cyan")
    table.add_column("Sources")

    for s in ranked:
        stale = " (price may be stale)" if s.price_stale else ""
        table.add_row(
            s.model_id,
            f"{s.quality * 100:.0f}%",
            f"${s.blended_per_m:.2f}{stale}",
            f"{s.quality_per_dollar:.3f}",
            ", ".join(s.sources) or "—",
        )
    console.print(table)
    console.print(
        "[dim]Ranking = task quality (mean of task-relevant public benchmarks, "
        "0–1) ÷ blended $/1M (3:1 input:output assumed). Higher is better.[/dim]"
    )
    if unranked:
        console.print(
            "\n[bold]No public priors for this task — benchmark with "
            "`costbench run`:[/bold]"
        )
        for p in unranked:
            note = f" — {p.notes}" if p.notes else ""
            console.print(f"  {p.model_id}{note}")
    if any("illustrative" in src for s in ranked for src in s.sources):
        console.print(
            "\n[yellow]⚠ The bundled priors are ILLUSTRATIVE PLACEHOLDERS "
            "(synthetic, not measured). Replace them with real, sourced numbers "
            "before relying on this ranking — see docs/PRIORS.md.[/yellow]"
        )
    console.print(
        "\n[dim]Priors are public-benchmark STARTING POINTS, not ground truth. "
        "The only ground truth is your own `costbench run` on your real cases. "
        "Sources and licenses: docs/PRIORS.md.[/dim]"
    )
