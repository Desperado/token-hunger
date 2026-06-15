import pytest

from costbench.models import ModelCatalog, _parse_catalog_text
from costbench.pricing import ModelPrice, PricingTable
from costbench.priors import (
    ArtificialAnalysisSource,
    load_priors,
    rank_models,
)

SEED = """
fast/cheap:
  priors:
    task_strengths: [coding]
    metrics:
      - name: humaneval
        value: 80.0
        unit: percent
        source: https://github.com/openai/human-eval
        license: MIT
        verified: 2026-06-06
slow/expensive:
  priors:
    task_strengths: [coding]
    metrics:
      - name: humaneval
        value: 90.0
        unit: percent
        source: https://github.com/openai/human-eval
        license: MIT
        verified: 2026-06-06
nopriors/local:
  priors:
    task_strengths: [coding]
    metrics: []
    notes: "run costbench to establish ground truth"
"""


def _seed_priors():
    return ModelCatalog(_parse_catalog_text(SEED)).priors()


def _pricing():
    return PricingTable({
        "fast/cheap": ModelPrice(0.10, 0.30, verified="2026-06-06"),
        "slow/expensive": ModelPrice(5.0, 15.0, verified="2026-06-06"),
        "nopriors/local": ModelPrice(0.5, 0.5, verified="2026-06-06"),
    })


def test_seed_parse():
    priors = _seed_priors()
    assert priors["fast/cheap"].metrics[0].name == "humaneval"
    assert priors["nopriors/local"].metrics == []


def test_quality_score_normalization():
    priors = _seed_priors()
    assert priors["slow/expensive"].quality_score("coding") == pytest.approx(0.90)
    assert priors["nopriors/local"].quality_score("coding") is None


def test_ranking_order_quality_per_dollar():
    priors = _seed_priors()
    ranked, unranked = rank_models("coding", priors, _pricing(), top=5)
    # fast/cheap has lower quality but much lower price -> higher quality-per-$
    assert ranked[0].model_id == "fast/cheap"
    assert ranked[1].model_id == "slow/expensive"
    assert [u.model_id for u in unranked] == ["nopriors/local"]


def test_aa_source_raises_optin_error():
    with pytest.raises(NotImplementedError, match="ARTIFICIAL_ANALYSIS_API_KEY"):
        ArtificialAnalysisSource().fetch_scores([])


def test_bundled_seed_loads():
    priors = load_priors("seed")
    assert "openai/gpt-5" in priors
    assert priors["anthropic/claude-opus-4-8"].metrics == []
    assert priors["anthropic/claude-fable-5"].metrics == []
    assert priors["gemini/gemini-3.1-pro-preview"].metrics == []
    assert priors["gemini/gemini-3.5-flash"].metrics == []
    assert priors["gemini/gemini-3-flash-preview"].metrics == []
    assert priors["gemini/gemini-3.1-flash-lite"].metrics == []
    assert "gemini/gemini-3-pro-preview" not in priors
    # local rows ship with no priors on purpose
    assert priors["local/gemma-27b"].metrics == []
