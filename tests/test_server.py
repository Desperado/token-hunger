"""Server payload tests — exercise the API builders directly (no socket).

These cover the offline paths (bootstrap + estimate). `run` needs provider
keys, so it is not exercised here; its shaping is covered by the runner tests.
"""

from costbench import server


def test_vendor_inference():
    assert server.vendor_of("anthropic/claude-haiku-4-5") == "Anthropic"
    assert server.vendor_of("openai/gpt-5") == "OpenAI"
    assert server.vendor_of("gemini/gemini-2.5-pro") == "Google"
    assert server.vendor_of("local/gemma-27b") == "Self-hosted"
    assert server.vendor_of("something-weird") == "Endpoint"


def test_bootstrap_payload_has_task_cases_and_priced_models():
    b = server.bootstrap_payload()
    assert b["task"]["check"] == "exact"
    assert b["task"]["system"]
    assert len(b["cases"]) == 24
    assert all("input" in c and "expect" in c for c in b["cases"])

    ids = {m["id"] for m in b["models"]}
    assert "anthropic/claude-haiku-4-5" in ids
    # vendor $/token models carry prices; amortized GPU models carry gpu/tput
    haiku = next(m for m in b["models"] if m["id"] == "anthropic/claude-haiku-4-5")
    assert haiku["basis"] == "vendor $/token" and haiku["inPrice"] > 0
    local = next(m for m in b["models"] if m["id"].startswith("local/"))
    assert local["basis"] == "amortized GPU (batch 1)" and local["gpu"] > 0

    assert b["meta"]["configFingerprint"].startswith("cfg:")
    assert b["meta"]["pricingFingerprint"].startswith("px:")


def test_estimate_payload_is_real_and_orders_by_price():
    boot = server.bootstrap_payload()
    body = {
        "task": boot["task"],
        "cases": boot["cases"],
        "targets": ["anthropic/claude-haiku-4-5", "anthropic/claude-opus-4-7"],
        "outputTokens": 8,
    }
    out = server.estimate_payload(body)
    rows = {r["id"]: r for r in out["rows"]}
    assert len(rows) == 2

    haiku = rows["anthropic/claude-haiku-4-5"]
    opus = rows["anthropic/claude-opus-4-7"]
    # real tokenizer/heuristic input counts, and a positive cost
    assert haiku["inTok"] > 0 and haiku["costHigh"] > 0
    assert not haiku["opaque"]
    # opus is strictly pricier per token, same task → higher estimate
    assert opus["costHigh"] > haiku["costHigh"]


def test_estimate_unknown_model_marked_unpriced():
    boot = server.bootstrap_payload()
    out = server.estimate_payload({
        "task": boot["task"],
        "cases": boot["cases"],
        "targets": ["acme/not-in-table"],
        "outputTokens": 8,
    })
    row = out["rows"][0]
    assert row["priced"] is False
    assert row["costHigh"] is None


def test_stream_run_emits_start_progress_and_result(monkeypatch):
    def fake_run_payload(body, case_progress=None):
        from costbench.runner import CaseProgress

        for i, (passed, error) in enumerate([(True, False), (False, True)]):
            case_progress(CaseProgress(
                target_id="fake/model",
                target_index=0,
                target_count=1,
                case_index=i,
                target_completed=i + 1,
                target_total=2,
                passed=passed,
                error=error,
            ))
        return {"rows": [], "meta": {"nCases": 2}}

    monkeypatch.setattr(server, "run_payload", fake_run_payload)
    events = []
    server.stream_run_payload(
        {"targets": ["fake/model"], "cases": [{}, {}], "concurrency": 2},
        events.append,
    )

    assert [e["type"] for e in events] == ["start", "progress", "progress", "result"]
    assert events[0]["total"] == 2
    assert events[1]["completed"] == 1
    assert events[2]["passes"] == 1
    assert events[2]["errors"] == 1
    assert events[2]["percent"] == 100.0
