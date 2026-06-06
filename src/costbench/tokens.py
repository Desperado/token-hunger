"""Keyless token counting for `costbench estimate`.

The whole point of estimate is to predict cost WITHOUT a key and WITHOUT
network. We count text with a provider-appropriate tokenizer when one is
available locally (tiktoken, mistral-common, HF transformers, deepseek), and
fall back to an over-estimate-safe heuristic otherwise.

Every tokenizer library is OPTIONAL and lazily imported inside its strategy
(mirroring the lazy `import litellm` in targets.py). costbench installed with no
extras still runs `estimate` via the heuristic. A missing optional lib NEVER
raises — we fall through to the heuristic and record the method honestly.

Resolution order: longest model_id prefix match, then provider prefix, then the
global heuristic fallback.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from typing import Callable, Optional

# CJK / Hangul block — these languages pack far more meaning per character, so a
# chars/4 divisor would badly UNDER-count tokens. We use a smaller divisor.
_CJK_RE = re.compile(r"[　-鿿가-힯]")
_CODE_HINTS = ("{", "}", ";", "def ", "function ")
_FOUR_SPACES = re.compile(r" {4,}")
_TIKTOKEN_LOCK = threading.Lock()


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    method: str        # "tiktoken:o200k_base" | "heuristic:chars/4" | ...
    exact: bool        # True only for a billing-grade tokenizer
    pad_applied: float  # 0.0 for exact; 0.10/0.20/... for padded heuristic


# --- the over-estimate-safe heuristic ---------------------------------------


def _heuristic(text: str, model_id: str, pad: float) -> TokenCount:
    """tokens = ceil(ceil(len/divisor) * (1 + pad)). Deterministic.

    Divisor by cheap content sniff:
      - any CJK char            -> 1.5  (and pad floored at 0.12)
      - looks like code/JSON    -> 3.5
      - else (prose)            -> 4.0
    When BOTH CJK and code trip, take the SMALLER divisor (more tokens) —
    over-estimate-safe.
    """
    is_cjk = bool(_CJK_RE.search(text))
    is_code = (
        any(h in text for h in _CODE_HINTS)
        or bool(_FOUR_SPACES.search(text))
        or "coder" in model_id.lower()
    )
    divisors = []
    if is_cjk:
        divisors.append(1.5)
        pad = max(pad, 0.12)
    if is_code:
        divisors.append(3.5)
    if not divisors:
        divisors.append(4.0)
    divisor = min(divisors)  # smaller divisor => more tokens => safer

    base = math.ceil(len(text) / divisor)
    tokens = math.ceil(base * (1 + pad))
    flavor = "cjk" if is_cjk else ("code" if is_code else "prose")
    return TokenCount(
        tokens=tokens,
        method=f"heuristic:chars/{divisor:g}+{int(round(pad * 100))}%({flavor})",
        exact=False,
        pad_applied=pad,
    )


# --- billing-grade strategies (all optional, lazily imported) ---------------


def _tiktoken_count(text: str, encoding: str) -> Optional[int]:
    try:
        import tiktoken  # lazy, optional
        import tiktoken.load as tiktoken_load
    except Exception:  # noqa: BLE001 — any import/runtime failure => fall back
        return None
    with _TIKTOKEN_LOCK:
        original_read_file = tiktoken_load.read_file

        def reject_cache_miss(path: str) -> bytes:
            raise OSError(f"offline tokenizer cache miss: {path}")

        tiktoken_load.read_file = reject_cache_miss
        try:
            enc = tiktoken.get_encoding(encoding)
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001
            return None
        finally:
            tiktoken_load.read_file = original_read_file


def _openai_strategy(text: str, model_id: str) -> TokenCount:
    n = _tiktoken_count(text, "o200k_base")
    if n is not None:
        return TokenCount(n, "tiktoken:o200k_base", exact=True, pad_applied=0.0)
    return _heuristic(text, model_id, pad=0.20)


def _proxy_strategy(text: str, model_id: str, pad: float, label: str) -> TokenCount:
    """tiktoken used as a PROXY for a provider with no keyless tokenizer.

    Not billing-grade (exact=False) and padded. Documented ±5% caveat for
    Anthropic; Gemini gets a larger pad."""
    n = _tiktoken_count(text, "o200k_base")
    if n is not None:
        padded = math.ceil(n * (1 + pad))
        return TokenCount(padded, label, exact=False, pad_applied=pad)
    return _heuristic(text, model_id, pad=max(pad, 0.20))


def _mistral_strategy(text: str, model_id: str) -> TokenCount:
    try:
        from mistral_common.tokens.tokenizers.mistral import (  # lazy, optional
            MistralTokenizer,
        )
        from mistral_common.protocol.instruct.request import ChatCompletionRequest
        from mistral_common.protocol.instruct.messages import UserMessage

        tok = MistralTokenizer.v3()
        req = ChatCompletionRequest(messages=[UserMessage(content=text)])
        n = len(tok.encode_chat_completion(req).tokens)
        return TokenCount(n, "mistral-common", exact=True, pad_applied=0.0)
    except Exception:  # noqa: BLE001
        return _heuristic(text, model_id, pad=0.15)


def _hf_strategy(text: str, model_id: str, hf_repo: str, pad: float) -> TokenCount:
    try:
        from transformers import AutoTokenizer  # lazy, optional

        tok = AutoTokenizer.from_pretrained(hf_repo, local_files_only=True)
        n = len(tok.encode(text))
        return TokenCount(n, f"hf:{hf_repo}", exact=True, pad_applied=0.0)
    except Exception:  # noqa: BLE001
        return _heuristic(text, model_id, pad=pad)


def _deepseek_strategy(text: str, model_id: str) -> TokenCount:
    try:
        import deepseek_tokenizer  # lazy, optional

        n = len(deepseek_tokenizer.encode(text))
        return TokenCount(n, "deepseek-tokenizer", exact=True, pad_applied=0.0)
    except Exception:  # noqa: BLE001
        return _heuristic(text, model_id, pad=0.15)


# --- registry: longest-prefix wins ------------------------------------------

# Each entry: (prefix, strategy callable taking (text, model_id)).
# Ordered by specificity; resolution sorts by prefix length descending.
_REGISTRY: list[tuple[str, Callable[[str, str], TokenCount]]] = [
    ("openai/", _openai_strategy),
    ("gemini/", lambda t, m: _proxy_strategy(t, m, 0.12, "tiktoken-proxy:o200k_base")),
    ("anthropic/", lambda t, m: _proxy_strategy(t, m, 0.10, "tiktoken-proxy:o200k_base")),
    ("mistral/", _mistral_strategy),
    ("deepseek/", _deepseek_strategy),
    ("qwen/", lambda t, m: _hf_strategy(t, m, "Qwen/Qwen2.5-7B-Instruct", 0.15)),
    ("local/qwen", lambda t, m: _hf_strategy(t, m, "Qwen/Qwen2.5-Coder-7B-Instruct", 0.15)),
    ("local/gemma", lambda t, m: _hf_strategy(t, m, "google/gemma-2-27b-it", 0.20)),
    ("local/", lambda t, m: _hf_strategy(t, m, "google/gemma-2-27b-it", 0.20)),
]


def count_input_tokens(text: str, model_id: str) -> TokenCount:
    """Count input tokens for `text` as billed to `model_id`.

    Billing-grade tokenizer if importable; otherwise the over-estimate-safe
    heuristic. Never raises on a missing optional library."""
    text = text or ""
    matches = [
        (prefix, fn) for prefix, fn in _REGISTRY if model_id.startswith(prefix)
    ]
    if matches:
        # longest prefix wins (most specific)
        prefix, fn = max(matches, key=lambda pf: len(pf[0]))
        return fn(text, model_id)
    return _heuristic(text, model_id, pad=0.20)


_TOKEN_BEARING_PARAMS = ("tools", "functions", "response_format")


def count_chat_input_tokens(
    system: Optional[str],
    prompt: str,
    model_id: str,
    params: Optional[dict] = None,
) -> TokenCount:
    """Estimate tokens for the actual chat request shape.

    Provider chat serialization is not stable enough to call this billing-exact
    across models. Count each message with the selected tokenizer, add
    conservative framing tokens, and include model-visible request schemas.
    """
    messages = []
    if system:
        messages.append(("system", system))
    messages.append(("user", prompt))

    counts = [count_input_tokens(content, model_id) for _, content in messages]
    total = sum(c.tokens for c in counts)
    total += 4 * len(messages) + 3

    visible_params = {
        key: params[key]
        for key in _TOKEN_BEARING_PARAMS
        if params and params.get(key) is not None
    }
    if visible_params:
        schema_text = json.dumps(
            visible_params,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        schema_count = count_input_tokens(schema_text, model_id)
        counts.append(schema_count)
        total += schema_count.tokens + 4

    methods = sorted({c.method for c in counts})
    return TokenCount(
        tokens=total,
        method=f"chat:{'+'.join(methods)}",
        exact=False,
        pad_applied=max((c.pad_applied for c in counts), default=0.0),
    )
