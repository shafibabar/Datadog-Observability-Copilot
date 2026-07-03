"""LLM client seam.

`LLMClient` is the interface the reasoning engine depends on, so tests inject a
fake and the engine never touches the network. Two real implementations sit
behind it:

- `AnthropicClient` — Claude via the Anthropic SDK (needs an ANTHROPIC_API_KEY);
  the underlying SDK client is injectable so even the wrapper is unit-tested.
- `ClaudeCliClient` — the "Claude Code way": shells out to the local `claude`
  CLI in headless mode, reusing the user's existing Claude Code login, so **no
  API key is required**. The subprocess runner is injectable so tests never
  spawn a real process.

`extract_json` robustly pulls a JSON object out of a model response (fenced or
prose-wrapped).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Callable, Protocol


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


def cli_available() -> bool:
    """True when the `claude` CLI is on PATH, so the keyless backend is usable.
    Never raises — safe to call during startup capability checks."""
    return shutil.which("claude") is not None


def _default_runner(cmd: list[str], timeout: float) -> str:
    """Run a subprocess and return its stdout, raising on a non-zero exit."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


class ClaudeCliClient:
    """Claude via the local `claude` CLI in headless (`-p`) mode.

    Uses the user's existing Claude Code authentication, so no API key is
    needed. `runner` is injectable so tests never spawn a real process.
    """

    def __init__(
        self,
        model_fast: str,
        model_deep: str,
        runner: Callable[[list[str], float], str] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._model_fast = model_fast
        self._model_deep = model_deep
        self._runner = runner or _default_runner
        self._timeout = timeout

    def complete(self, system: str, user: str, deep: bool = False) -> str:
        model = self._model_deep if deep else self._model_fast
        cmd = [
            "claude",
            "-p", user,
            "--append-system-prompt", system,
            "--model", model,
            "--output-format", "text",
        ]
        return self._runner(cmd, self._timeout).strip()
