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


def test_bundled_catalog_loads_with_local_entries():
    from costbench.pricing import load_pricing

    table = load_pricing()
    prices = {mid: table.get(mid) for mid in table.ids()}
    assert isinstance(prices["local/gemma-27b"], AmortizedGpuPrice)
    assert isinstance(prices["mistral/mistral-large-3"], ModelPrice)
    opus = prices["anthropic/claude-opus-4-8"]
    assert isinstance(opus, ModelPrice)
    assert opus.input_per_m == 5.0
    assert opus.output_per_m == 25.0
    fable = prices["anthropic/claude-fable-5"]
    assert isinstance(fable, ModelPrice)
    assert fable.input_per_m == 10.0
    assert fable.output_per_m == 50.0
    gemini_pro = prices["gemini/gemini-3.1-pro-preview"]
    assert isinstance(gemini_pro, ModelPrice)
    assert gemini_pro.input_per_m == 2.0
    assert gemini_pro.output_per_m == 12.0
    gemini_new_flash = prices["gemini/gemini-3.5-flash"]
    assert isinstance(gemini_new_flash, ModelPrice)
    assert gemini_new_flash.input_per_m == 1.5
    assert gemini_new_flash.output_per_m == 9.0
    gemini_flash = prices["gemini/gemini-3-flash-preview"]
    assert isinstance(gemini_flash, ModelPrice)
    assert gemini_flash.input_per_m == 0.5
    assert gemini_flash.output_per_m == 3.0
    gemini_flash_lite = prices["gemini/gemini-3.1-flash-lite"]
    assert isinstance(gemini_flash_lite, ModelPrice)
    assert gemini_flash_lite.input_per_m == 0.25
    assert gemini_flash_lite.output_per_m == 1.5
    assert "gemini/gemini-3-pro-preview" not in prices
    qwen37_max = prices["qwen/qwen3.7-max"]
    assert isinstance(qwen37_max, ModelPrice)
    assert qwen37_max.input_per_m == 2.50
    assert qwen37_max.output_per_m == 7.50
    qwen37_plus = prices["qwen/qwen3.7-plus"]
    assert isinstance(qwen37_plus, ModelPrice)
    assert qwen37_plus.input_per_m == 0.40
    assert qwen37_plus.output_per_m == 1.60
    assert "qwen/qwen-turbo" not in prices
    assert "qwen/qwq-plus" not in prices
    # whole table fingerprints without error (covers mixed-basis canonicalization)
    PricingTable(prices)
