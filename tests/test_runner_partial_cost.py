"""A single unpriced/errored case must not null the whole target's cost.

We sum the KNOWN costs, surface 'k of n unpriced', and divide cost_per_run by
the number of PRICED cases (not n)."""

import pytest

from costbench.runner import CaseResult, TargetResult


def _case(cost):
    return CaseResult(
        case_input="in",
        expect="x",
        output="x",
        passed=True,
        detail="",
        cost=cost,
        cost_basis="$/token" if cost is not None else "unknown",
        latency=0.0,
    )


def test_partial_cost_sums_known_and_counts_unpriced():
    tr = TargetResult(target_id="t", target_type="model")
    tr.cases = [_case(0.01), _case(None), _case(0.03)]

    assert tr.n == 3
    assert tr.n_priced == 2
    assert tr.n_unpriced == 1
    assert tr.cost_known is True
    assert tr.total_cost == pytest.approx(0.04)
    # cost_per_run divides by the 2 priced cases, not 3.
    assert tr.cost_per_run == pytest.approx(0.02)
    # cost_per_success divides known cost by passes (all 3 passed).
    assert tr.cost_per_success == pytest.approx(0.04 / 3)


def test_all_unpriced_is_none():
    tr = TargetResult(target_id="t", target_type="model")
    tr.cases = [_case(None), _case(None)]

    assert tr.n_priced == 0
    assert tr.cost_known is False
    assert tr.total_cost is None
    assert tr.cost_per_run is None
    assert tr.cost_per_success is None


def test_token_fields_default_none():
    c = _case(0.01)
    assert c.input_tokens is None
    assert c.output_tokens is None
