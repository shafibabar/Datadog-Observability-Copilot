"""Tolerant loader for the shipped EC knowledge files.

Nothing here may raise on bad input. The knowledge layer is an enhancement: if a
file is missing, truncated, or hand-edited into invalid JSON, the copilot must
fall back to its previous behaviour rather than fail to start. Failures are
recorded on the KnowledgeBase so `/api/status` and diagnostics can report them
instead of the problem being silent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Where the committed knowledge files live.
DATA_DIR = Path(__file__).parent / "data"

#: Logical name -> `<name>.json`. Each is also an attribute on KnowledgeBase.
SOURCES: tuple[str, ...] = (
    "monitors_dictionary",
    "nlp_grammar",
    "metrics_nlp",
    "examples",
    "errors",
)


@dataclass
class KnowledgeBase:
    """The parsed knowledge files, each defaulting to `{}` when unavailable."""

    monitors_dictionary: dict = field(default_factory=dict)
    nlp_grammar: dict = field(default_factory=dict)
    metrics_nlp: dict = field(default_factory=dict)
    examples: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)

    #: Names that parsed successfully, in SOURCES order.
    loaded: tuple[str, ...] = ()
    #: {name: reason} for anything that could not be used.
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.loaded


def load_knowledge(data_dir: Path | str | None = None) -> KnowledgeBase:
    """Load every available source from `data_dir` (defaults to the shipped set).

    A missing directory yields an empty base. A file that is absent, unreadable,
    not valid JSON, or not a JSON *object* is skipped and recorded in `failed` —
    consumers index these by key, so a bare array or scalar is unusable.
    """
    directory = Path(data_dir) if data_dir is not None else DATA_DIR
    kb = KnowledgeBase()
    if not directory.is_dir():
        return kb

    loaded: list[str] = []
    for name in SOURCES:
        path = directory / f"{name}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            kb.failed[name] = f"unreadable or invalid JSON: {exc}"
            continue
        if not isinstance(data, dict):
            kb.failed[name] = f"expected a JSON object, got {type(data).__name__}"
            continue
        setattr(kb, name, data)
        loaded.append(name)

    kb.loaded = tuple(loaded)
    return kb
