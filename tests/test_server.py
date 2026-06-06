"""Server payload tests — exercise the API builders directly (no socket).

These cover the offline paths (bootstrap + estimate). `run` needs provider
keys, so it is not exercised here; its shaping is covered by the runner tests.
"""

import sys
from types import SimpleNamespace

import pytest

from costbench import server
from costbench.history import Observation, append_observations


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
    assert "anthropic/claude-opus-4-8" in ids
    assert "anthropic/claude-sonnet-4-6" in ids
    assert "anthropic/claude-haiku-4-6" not in ids
    assert "gemini/gemini-3.1-pro-preview" in ids
    assert "gemini/gemini-3.5-flash" in ids
    assert "gemini/gemini-3-flash-preview" in ids
    assert "gemini/gemini-3.1-flash-lite" in ids
    assert "gemini/gemini-3-pro-preview" not in ids
    # vendor $/token models carry prices; amortized GPU models carry gpu/tput
    haiku = next(m for m in b["models"] if m["id"] == "anthropic/claude-haiku-4-5")
    assert haiku["basis"] == "vendor $/token" and haiku["inPrice"] > 0
    local = next(m for m in b["models"] if m["id"].startswith("local/"))
    assert local["basis"] == "amortized GPU (batch 1)" and local["gpu"] > 0

    assert b["meta"]["configFingerprint"].startswith("cfg:")
    assert b["meta"]["pricingFingerprint"].startswith("px:")
    qualitymax = next(c for c in b["connectors"] if c["id"] == "qualitymax")
    assert qualitymax["status"] in {"available", "installed"}


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


def test_estimate_uses_imported_dataset_fingerprint(monkeypatch, tmp_path):
    history = tmp_path / "history.jsonl"
    append_observations(
        [
            Observation(
                config_fingerprint="0123456789ab",
                target_id="anthropic/claude-haiku-4-5",
                model_id="claude-haiku-4-5",
                input_tokens=100 + i,
                output_tokens=10 + i,
                cost=0.001,
                passed=False,
                ts="2026-06-06T00:00:00Z",
            )
            for i in range(5)
        ],
        path=history,
    )
    monkeypatch.setenv("COSTBENCH_HISTORY", str(history))

    out = server.estimate_payload({
        "task": {
            "system": "Predict completed or failed.",
            "promptTemplate": "{input}",
            "check": "exact",
        },
        "cases": [{"input": "crawl", "expect": "completed"}],
        "targets": ["anthropic/claude-haiku-4-5"],
        "configFingerprint": "0123456789ab",
    })

    assert out["rows"][0]["calibrated"] is True


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


def test_public_host_relaxes_guards_for_hosted_deploy(monkeypatch):
    # Without COSTBENCH_PUBLIC_HOST the loopback-only guards stand.
    monkeypatch.delenv("COSTBENCH_PUBLIC_HOST", raising=False)
    assert not server._is_allowed_origin("https://costbench.up.railway.app")

    # With it set, that exact host is allowed (bind + origin), others still rejected.
    monkeypatch.setenv("COSTBENCH_PUBLIC_HOST", "costbench.up.railway.app")
    assert server._is_allowed_origin("https://costbench.up.railway.app")
    assert not server._is_allowed_origin("https://attacker.example")
    assert server._is_loopback_host("127.0.0.1")  # loopback still allowed too
    # Host-header guard relaxes for the same public host.
    assert server._is_local_http_authority("costbench.up.railway.app")
    assert server._is_local_http_authority("127.0.0.1:8765")
    assert not server._is_local_http_authority("attacker.example")


def test_self_hosted_models_use_authenticated_ollama_endpoints(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://llm.example")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3:27b-it-q4_K_M")
    monkeypatch.setenv("OLLAMA_QWEN_MODEL", "qwen3:14b")

    cfg = server._build_cfg(
        {"system": "Classify.", "promptTemplate": "{input}", "check": "exact"},
        ["local/gemma-27b", "local/qwen-coder"],
        [{"input": "case", "expect": "completed"}],
    )

    gemma, qwen = cfg.targets
    assert gemma.type == "endpoint"
    assert gemma.raw["url"] == "https://llm.example/api/generate"
    assert gemma.raw["request_template"]["model"] == "gemma3:27b-it-q4_K_M"
    assert gemma.raw["auth_scheme"] == "basic"
    assert gemma.raw["token_priced"] is True
    assert qwen.raw["url"] == "https://llm.example/api/generate"
    assert qwen.raw["request_template"]["model"] == "qwen3:14b"
    assert qwen.raw["request_template"]["think"] is False


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
    with pytest.raises(ValueError, match="web checks"):
        server.validate_request(
            "/api/run",
            {
                **valid,
                "task": {
                    **valid["task"],
                    "check": {"type": "code", "function": "/tmp/evil.py:run"},
                },
            },
        )
    with pytest.raises(ValueError, match="unsupported numeric check option"):
        server.validate_request(
            "/api/run",
            {
                **valid,
                "task": {
                    **valid["task"],
                    "check": {"type": "numeric", "function": "evil"},
                },
            },
        )
    with pytest.raises(ValueError, match="target/case calls"):
        server.validate_request(
            "/api/run",
            {
                **valid,
                "targets": [
                    f"model/{i}" for i in range(server.MAX_RUNS // 1000 + 1)
                ],
                "cases": [{"input": "q", "expect": "a"}] * 1000,
            },
        )
    with pytest.raises(ValueError, match="configFingerprint"):
        server.validate_request(
            "/api/run",
            {**valid, "configFingerprint": "../../history"},
        )


def test_build_cfg_accepts_trusted_dataset_fingerprint():
    cfg = server._build_cfg(
        {"system": "Answer.", "promptTemplate": "{input}", "check": "exact"},
        ["anthropic/claude-haiku-4-5"],
        [{"input": "q", "expect": "a"}],
        config_fingerprint="0123456789ab",
    )
    assert cfg.fingerprint == "0123456789ab"


def test_predicted_uses_leading_label_when_exact_format_check_fails():
    output = "CLARIFY\n\nThe request is coherent but missing a required value."

    predicted = server._predicted(
        output,
        "CLARIFY",
        False,
        ["ANSWERABLE", "CLARIFY", "CONTRADICTORY", "NONSENSE"],
    )

    assert predicted == "CLARIFY"


def test_static_path_containment_guard_logic():
    root = server.UI_DIR.resolve()
    assert root in (root / "styles.css").resolve().parents
    assert root not in (root / "../pricing.yaml").resolve().parents


# --- e2b sandbox run from the UI ------------------------------------------


def _install_fake_e2b(monkeypatch):
    class _Sandbox:
        instances = []

        def __init__(self):
            self.written = {}
            self.killed = False
            _Sandbox.instances.append(self)

        @classmethod
        def create(cls, template=None):
            return cls()

        def kill(self):
            self.killed = True

        @property
        def files(self):
            sbx = self

            class _Files:
                def write(self, path, content):
                    sbx.written[path] = content

            return _Files()

        @property
        def commands(self):
            class _Commands:
                def run(self, cmd, timeout=None):
                    return SimpleNamespace(exit_code=0, stdout="ANSWER\n", stderr="")

            return _Commands()

    monkeypatch.setitem(sys.modules, "e2b", SimpleNamespace(Sandbox=_Sandbox))
    monkeypatch.setenv("E2B_API_KEY", "test-key")
    from costbench.targets import E2BCommandTarget
    E2BCommandTarget._next_create_at = 0.0
    _Sandbox.instances = []
    return _Sandbox


def test_sandbox_run_validation_relaxes_targets_and_checks_fields():
    body = {
        "task": {"promptTemplate": "{input}", "check": "exact"},
        "cases": [{"input": "q", "expect": "ANSWER"}],
        "sandbox": {"command": "cat", "perSecond": 0.0000325, "poolSize": 5},
    }
    # targets not required when a sandbox block is present
    assert server.validate_request("/api/run", body) is body

    bad = lambda sb: server.validate_request("/api/run", {**body, "sandbox": sb})
    with pytest.raises(ValueError, match="sandbox.command"):
        bad({"command": "", "perSecond": 0.1})
    with pytest.raises(ValueError, match="perSecond"):
        bad({"command": "cat", "perSecond": 0})
    with pytest.raises(ValueError, match="poolSize"):
        bad({"command": "cat", "perSecond": 0.1, "poolSize": 99})


def test_build_cfg_builds_e2b_command_target():
    cfg = server._build_cfg(
        {"promptTemplate": "{input}", "check": "exact"},
        [],
        [{"input": "q", "expect": "a"}],
        sandbox={"command": "cat", "perSecond": 0.0000325, "poolSize": 7, "template": "tmpl"},
    )
    assert len(cfg.targets) == 1
    target = cfg.targets[0]
    assert target.type == "command"
    assert target.raw["sandbox"] == "e2b"
    assert target.raw["sandbox_template"] == "tmpl"
    assert target.raw["sandbox_pool_size"] == 7
    assert target.cost.basis == "per_second"
    assert target.cost.per_second == 0.0000325


def test_estimate_skips_sandbox():
    out = server.estimate_payload({
        "task": {"promptTemplate": "{input}", "check": "exact"},
        "cases": [{"input": "q", "expect": "a"}],
        "sandbox": {"command": "cat", "perSecond": 0.001},
    })
    assert out["rows"] == []
    assert out["meta"]["sandbox"] is True


def test_sandbox_run_payload_executes_and_costs(monkeypatch):
    fake = _install_fake_e2b(monkeypatch)
    out = server.run_payload({
        "task": {"promptTemplate": "{input}", "check": "exact"},
        "cases": [{"input": "x", "expect": "ANSWER"}],
        "sandbox": {"command": "cat", "perSecond": 0.001, "poolSize": 2},
        "concurrency": 2,
    })
    rows = out["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "command"
    assert row["passes"] == 1 and row["n"] == 1
    assert row["priced"] is True  # measured e2b cost finalized at close()
    assert fake.instances and all(s.killed for s in fake.instances)
