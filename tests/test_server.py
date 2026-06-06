"""Server payload tests — exercise the API builders directly (no socket).

These cover the offline paths (bootstrap + estimate). `run` needs provider
keys, so it is not exercised here; its shaping is covered by the runner tests.
"""

from costbench import server
import pytest


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


def test_server_refuses_non_loopback_bind():
    assert server._is_loopback_host("127.0.0.1")
    assert server._is_loopback_host("::1")
    assert server._is_loopback_host("localhost")
    assert not server._is_loopback_host("0.0.0.0")
    with pytest.raises(ValueError, match="local-only"):
        server.serve(host="0.0.0.0", port=0, open_browser=False)
    assert server._is_local_http_authority("127.0.0.1:8765")
    assert server._is_local_http_authority("[::1]:8765")
    assert server._is_local_http_authority("localhost:8765")
    assert not server._is_local_http_authority("attacker.example:8765")
    assert server._is_allowed_origin("http://127.0.0.1:8765")
    assert not server._is_allowed_origin("https://attacker.example")


def test_request_validation_rejects_bad_shapes_and_limits():
    valid = {
        "task": {"system": "Answer.", "promptTemplate": "{input}", "check": "exact"},
        "targets": ["example/model"],
        "cases": [{"input": "question", "expect": "answer"}],
    }
    assert server.validate_request("/api/run", valid) is valid

    with pytest.raises(ValueError, match="JSON object"):
        server.validate_request("/api/run", [])
    with pytest.raises(ValueError, match="non-empty"):
        server.validate_request("/api/run", {**valid, "targets": []})
    with pytest.raises(ValueError, match="between 1 and 32"):
        server.validate_request("/api/run", {**valid, "concurrency": 100})
    with pytest.raises(ValueError, match="must be a scalar"):
        server.validate_request(
            "/api/run",
            {**valid, "cases": [{"input": "q", "expect": {"nested": True}}]},
        )
    with pytest.raises(ValueError, match="target/case calls"):
        server.validate_request(
            "/api/run",
            {
                **valid,
                "targets": [f"model/{i}" for i in range(11)],
                "cases": [{"input": "q", "expect": "a"}] * 1000,
            },
        )


def test_static_path_containment_guard_logic():
    root = server.UI_DIR.resolve()
    assert root in (root / "styles.css").resolve().parents
    assert root not in (root / "../pricing.yaml").resolve().parents
