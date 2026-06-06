from costbench.pricing import ModelPrice, PricingTable


def test_model_price_computes_token_cost():
    price = ModelPrice(input_per_m=1.0, output_per_m=5.0)
    assert price.cost(1_000_000, 200_000) == 2.0


def test_overrides_do_not_mutate_original_table():
    original = PricingTable({"model": ModelPrice(1.0, 2.0)})
    overridden = original.with_overrides({"model": {"input": 3, "output": 4}})

    assert original.get("model").input_per_m == 1.0
    assert overridden.get("model").input_per_m == 3.0
    assert original.fingerprint != overridden.fingerprint
