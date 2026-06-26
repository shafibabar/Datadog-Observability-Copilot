"""LLM client seam.

`LLMClient` is the interface the reasoning engine depends on, so tests inject a
fake and the engine never touches the network. `AnthropicClient` is the real
implementation (Claude via the Anthropic SDK); the underlying SDK client is
injectable so even the wrapper is unit-tested without a key. `extract_json`
robustly pulls a JSON object out of a model response (fenced or prose-wrapped).
"""
from __future__ import annotations

import json
import re
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, system: str, user: str, deep: bool = False) -> str: ...


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL)


def extract_json(text: str) -> dict | list:
    """Parse a JSON object/array from a possibly prose-wrapped model response."""
    text = text.strip()
    candidate: str | None = None

    m = _FENCE_RE.search(text)
    if m:
        candidate = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            candidate = text[start:end + 1]

    if candidate is None:
        raise ValueError("No JSON found in model response")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in model response: {exc}") from exc


class AnthropicClient:
    """Real Claude client. `client` is injectable for testing."""

    def __init__(
        self,
        api_key: str,
        model_fast: str,
        model_deep: str,
        client: object | None = None,
        max_tokens: int = 2000,
    ) -> None:
        if client is None:
            import anthropic  # imported lazily so non-LLM paths don't need it
            client = anthropic.Anthropic(api_key=api_key)
        self._client = client
        self._model_fast = model_fast
        self._model_deep = model_deep
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str, deep: bool = False) -> str:
        model = self._model_deep if deep else self._model_fast
        msg = self._client.messages.create(
            model=model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(block, "text", "") for block in msg.content)
