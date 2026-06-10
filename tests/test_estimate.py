import pytest

from costbench.config import Case, Config, CostSpec, TargetSpec, TaskSpec
from costbench.estimate import estimate_config
from costbench.history import Observation
from costbench.limits import load_model_limits
from costbench.pricing import ModelPrice, PricingTable


def _config(targets, cases=None, system=None):
    return Config(
        name="est-test",
        targets=targets,
        task=TaskSpec(system=system, prompt_template="Classify: {input}"),
        check="exact",
        cases=cases or [Case("ticket one", "X"), Case("ticket two", "Y")],
        fingerprint="cfgfp",
    )


def _pricing():
    return PricingTable({"openai/gpt-5": ModelPrice(1.25, 10.0, verified="2026-06-06")})


def _model_target(tid="openai/gpt-5", raw=None):
    return TargetSpec(type="model", id=tid, raw=raw or {"type": "model", "id": tid})


def test_priced_model_ceiling_range():
    cfg = _config([_model_target()])
    limits = load_model_limits()
    ests = estimate_config(cfg, _pricing(), limits)
    e = ests[0]
    assert e.priced is True
    assert e.cost_basis == "estimated (worst-case ceiling)"
    assert e.input_cost_total is not None and e.input_cost_total > 0
    # uncalibrated -> output low == high (ceiling)
    assert e.output_cost_low == e.output_cost_high
    assert e.calibrated is False


def test_opus_4_8_uses_bundled_128k_output_limit():
    pricing = PricingTable({
        "anthropic/claude-opus-4-8": ModelPrice(
            5.0,
            25.0,
            verified="2026-06-06",
        )
    })
    cfg = _config([_model_target("anthropic/claude-opus-4-8")])

    estimate = estimate_config(cfg, pricing, load_model_limits())[0]

    assert estimate.output_ceiling == 128000
    assert estimate.ceiling_source == "model_limits.yaml"


def test_fable_5_uses_bundled_128k_output_limit():
    pricing = PricingTable({
        "anthropic/claude-fable-5": ModelPrice(
            10.0,
            50.0,
            verified="2026-06-10",
        )
    })
    cfg = _config([_model_target("anthropic/claude-fable-5")])

    estimate = estimate_config(cfg, pricing, load_model_limits())[0]

    assert estimate.output_ceiling == 128000
    assert estimate.ceiling_source == "model_limits.yaml"


@pytest.mark.parametrize(
    "model_id",
    [
        "gemini/gemini-3.1-pro-preview",
        "gemini/gemini-3.5-flash",
        "gemini/gemini-3-flash-preview",
        "gemini/gemini-3.1-flash-lite",
    ],
)
def test_gemini_3_models_use_bundled_64k_output_limit(model_id):
    pricing = PricingTable({model_id: ModelPrice(1.0, 1.0)})
    cfg = _config([_model_target(model_id)])

    estimate = estimate_config(cfg, pricing, load_model_limits())[0]

    assert estimate.output_ceiling == 65536
    assert estimate.ceiling_source == "model_limits.yaml"


def test_unpriced_model_flagged():
    cfg = _config([_model_target("openai/unknown-x")])
    ests = estimate_config(cfg, _pricing(), load_model_limits())
    e = ests[0]
    assert e.priced is False
    assert "no price" in e.cost_basis
    assert e.input_cost_total is None


def test_max_output_override_changes_ceiling():
    cfg = _config([_model_target()])
    limits = load_model_limits()
    low = estimate_config(cfg, _pricing(), limits, max_output_override=10)[0]
    high = estimate_config(cfg, _pricing(), limits, max_output_override=10000)[0]
    assert high.output_cost_high > low.output_cost_high
    assert low.output_ceiling == 10


def test_params_max_tokens_used_as_ceiling():
    t = _model_target(raw={"type": "model", "id": "openai/gpt-5",
                           "params": {"max_tokens": 7}})
    cfg = _config([t])
    e = estimate_config(cfg, _pricing(), load_model_limits())[0]
    assert e.output_ceiling == 7
    assert "params.max_tokens" in e.ceiling_source


def test_params_max_completion_tokens_used_as_ceiling():
    t = _model_target(
        raw={
            "type": "model",
            "id": "openai/gpt-5",
            "params": {"max_completion_tokens": 9},
        }
    )
    cfg = _config([t])
    e = estimate_config(cfg, _pricing(), load_model_limits())[0]
    assert e.output_ceiling == 9
    assert "params.max_completion_tokens" in e.ceiling_source


@pytest.mark.parametrize("value", [0, -1, 1.5])
def test_rejects_nonpositive_output_override(value):
    cfg = _config([_model_target()])

    with pytest.raises(ValueError, match="positive integer"):
        estimate_config(
            cfg,
            _pricing(),
            load_model_limits(),
            max_output_override=value,
        )


def test_rejects_nonpositive_config_output_ceiling():
    t = _model_target(
        raw={
            "type": "model",
            "id": "openai/gpt-5",
            "params": {"max_tokens": -5},
        }
    )

    with pytest.raises(ValueError, match="params.max_tokens"):
        estimate_config(_config([t]), _pricing(), load_model_limits())


def test_calibrated_range_with_history():
    cfg = _config([_model_target()])
    obs = [
        Observation("cfgfp", "openai/gpt-5", "openai/gpt-5", 100, out, 0.001, True,
                    "2026-06-06T00:00:00Z")
        for out in [10, 20, 30, 40, 50]
    ]
    e = estimate_config(cfg, _pricing(), load_model_limits(), history=obs)[0]
    assert e.calibrated is True
    assert e.cost_basis == "estimated (calibrated p50–p90)"
    assert e.output_cost_low < e.output_cost_high


def test_blackbox_endpoint_uses_declared_cost():
    t = TargetSpec(
        type="endpoint",
        id="https://api.example.com",
        raw={"type": "endpoint", "url": "https://api.example.com"},
        cost=CostSpec(basis="per_request", per_request=0.02),
    )
    cfg = _config([t])
    e = estimate_config(cfg, _pricing(), load_model_limits())[0]
    assert e.priced is True
    assert e.per_case_high == 0.02
    assert e.input_cost_total is None  # never tokenize a black box


def test_blackbox_no_cost_not_priced():
    t = TargetSpec(type="command", id="local-cmd",
                   raw={"type": "command", "command": "x"}, cost=CostSpec())
    cfg = _config([t])
    e = estimate_config(cfg, _pricing(), load_model_limits())[0]
    assert e.priced is False
    assert "declare a cost basis" in (e.note or "")


def test_system_prompt_increases_input_tokens():
    base = estimate_config(_config([_model_target()]), _pricing(),
                           load_model_limits())[0]
    withsys = estimate_config(
        _config([_model_target()], system="You are a careful classifier. " * 5),
        _pricing(), load_model_limits())[0]
    assert withsys.input_cost_total > base.input_cost_total
