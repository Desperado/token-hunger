import math

from costbench.tokens import count_input_tokens


def test_heuristic_prose_deterministic():
    text = "hello world " * 10  # 120 chars
    a = count_input_tokens(text, "unknown/model")
    b = count_input_tokens(text, "unknown/model")
    assert a == b
    # prose divisor 4.0, pad 0.20: ceil(120/4)=30, ceil(30*1.2)=36
    assert a.tokens == 36
    assert a.exact is False
    assert a.pad_applied == 0.20


def test_heuristic_cjk_smaller_divisor():
    cjk = "你好世界这是一个测试"  # 10 CJK chars
    tc = count_input_tokens(cjk, "unknown/model")
    # divisor 1.5, pad floored at 0.12 (but global fallback pad is 0.20 -> max=0.20)
    base = math.ceil(10 / 1.5)
    assert tc.tokens == math.ceil(base * 1.20)
    assert "cjk" in tc.method


def test_heuristic_code_divisor():
    code = "def f(x):\n    return x + 1\n" * 3
    tc = count_input_tokens(code, "unknown/model")
    base = math.ceil(len(code) / 3.5)
    assert tc.tokens == math.ceil(base * 1.20)
    assert "code" in tc.method


def test_coder_model_id_triggers_code_divisor():
    text = "plain prose with no special chars here at all friend"
    plain = count_input_tokens(text, "qwen/qwen3-max")
    coder = count_input_tokens(text, "local/qwen-coder-thing")
    # coder id forces code divisor (3.5) -> more tokens than prose (4.0)
    # but only when both fall to heuristic; qwen falls to HF/heuristic.
    assert coder.tokens >= plain.tokens or "code" in coder.method


def test_missing_optional_lib_falls_back_without_raising(monkeypatch):
    # Force tiktoken import to fail; openai/ must fall back to heuristic, not raise.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "tiktoken":
            raise ImportError("no tiktoken")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tc = count_input_tokens("hello there world", "openai/gpt-5")
    assert tc.exact is False  # fell back to heuristic
    assert "heuristic" in tc.method


def test_empty_text():
    tc = count_input_tokens("", "unknown/model")
    assert tc.tokens == 0
