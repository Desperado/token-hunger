from costbench.models import load_catalog
from costbench.pricing import load_pricing
from costbench.limits import load_model_limits
from costbench.priors import load_priors


def test_catalog_unifies_pricing_limits_and_priors():
    catalog = load_catalog()
    ids = catalog.ids()
    assert "qwen/qwen3.7-max" in ids
    assert "anthropic/claude-haiku-4-5" in ids

    pricing_ids = set(load_pricing().ids())
    limits_ids = set(load_model_limits())
    priors_ids = set(load_priors().keys())

    assert pricing_ids <= set(ids)
    assert limits_ids <= set(ids)
    assert priors_ids <= set(ids)
    assert "qwen/qwen-turbo" not in pricing_ids


def test_legacy_flat_pricing_yaml_still_loads(tmp_path):
    path = tmp_path / "custom-pricing.yaml"
    path.write_text(
        "custom/model:\n  input: 1.0\n  output: 2.0\n",
        encoding="utf-8",
    )
    table = load_pricing(path)
    price = table.get("custom/model")
    assert price.input_per_m == 1.0
    assert price.output_per_m == 2.0
