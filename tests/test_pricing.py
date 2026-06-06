import pytest

from costbench.pricing import (
    AmortizedGpuPrice,
    ModelPrice,
    PricingTable,
    _load_yaml_text,
    _parse_entry,
)


def test_model_price_computes_token_cost():
    price = ModelPrice(input_per_m=1.0, output_per_m=5.0)
    assert price.cost(1_000_000, 200_000) == 2.0


def test_overrides_do_not_mutate_original_table():
    original = PricingTable({"model": ModelPrice(1.0, 2.0)})
    overridden = original.with_overrides({"model": {"input": 3, "output": 4}})

    assert original.get("model").input_per_m == 1.0
    assert overridden.get("model").input_per_m == 3.0
    assert original.fingerprint != overridden.fingerprint


def test_parse_amortized_gpu_entry_and_cost_formula():
    entry = {
        "basis": "amortized_gpu",
        "gpu_hourly_rate": 3.6,
        "throughput_tokens_per_sec": 1000,
        "verified": "2026-06-06",
        "source": "https://example.com",
    }
    price = _parse_entry("local/x", entry)
    assert isinstance(price, AmortizedGpuPrice)
    # per_token = 3.6 / 1000 / 3600 = 1e-6
    assert price.per_token == pytest.approx(1e-6)
    # cost = (input + output) * per_token
    assert price.cost(500_000, 500_000) == pytest.approx(1.0)
    assert price.cost_basis_label == "amortized GPU (batch 1)"


def test_amortized_gpu_rejects_nonpositive():
    with pytest.raises(ValueError):
        _parse_entry("local/x", {"basis": "amortized_gpu",
                                 "gpu_hourly_rate": 0, "throughput_tokens_per_sec": 1})


def test_amortized_gpu_infra_override():
    price = AmortizedGpuPrice(gpu_hourly_rate=1.0, throughput_tokens_per_sec=100)
    overridden = price.with_infra(gpu_hourly_rate=2.0)
    assert overridden.gpu_hourly_rate == 2.0
    assert overridden.throughput_tokens_per_sec == 100
    assert price.gpu_hourly_rate == 1.0  # original unchanged


def test_bundled_pricing_yaml_loads_with_local_entries():
    from importlib import resources

    text = resources.files("costbench").joinpath("pricing.yaml").read_text(
        encoding="utf-8"
    )
    prices = _load_yaml_text(text)
    assert isinstance(prices["local/gemma-27b"], AmortizedGpuPrice)
    assert isinstance(prices["mistral/mistral-large-3"], ModelPrice)
    # whole table fingerprints without error (covers mixed-basis canonicalization)
    PricingTable(prices)
