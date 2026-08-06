"""Structured reasoning objects.

Every conclusion the AI produces is one of four categories, carries a confidence,
and points to evidence by id. Root-cause hypotheses are first-class objects that
*require* contradicting-evidence and missing-information fields, so the model is
forced to surface what would disprove it, not only what supports it.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.telemetry.models import TelemetryEvent


class ReasoningCategory(str, Enum):
    FACT = "fact"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @classmethod
    def parse(cls, value: object) -> "Confidence":
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.MEDIUM

    @property
    def rank(self) -> int:
        """Confidence ordering (LOW < MEDIUM < HIGH) so callers can sort/compare
        without re-encoding the order (e.g. picking the strongest hypothesis)."""
        return {"low": 0, "medium": 1, "high": 2}[self.value]


class Evidence(BaseModel):
    """A pointer from a claim down to the underlying telemetry.

    `detail` is the prose form handed to the model. The structured fields
    beside it are what the reply and the Workspace panel actually render:
    re-parsing numbers back out of a sentence would be fragile, and a reply
    built from parsed prose could disagree with the telemetry it came from.
    """

    id: str            # catalog id, e.g. "evt:e1" or "met:api.latency.p95"
    kind: str          # "event" | "metric"
    ref: str           # the event id or metric name
    detail: str        # human-readable, drillable description

    # Attribution — which part of the platform produced this.
    service: str | None = None
    stage: str | None = None   # lifecycle position, e.g. "8 indexed"

    # Metric shape. `has_data` distinguishes "queried and empty" from
    # "never queried"; a metric with no data is still citable, for an Unknown.
    has_data: bool = True
    points: int = 0
    unit: str = ""
    baseline: float | None = None
    latest: float | None = None
    extreme: float | None = None

    # Event shape.
    time: str = ""
    severity: str = ""


class CoverageGap(BaseModel):
    """Something the question asked about that no monitor can answer.

    Recorded deterministically from the monitors dictionary rather than asked
    of the model, so it can never be quietly omitted from a confident answer.
    """

    topic: str
    kind: str          # "no_monitor" | "no_data_trap"
    reason: str = ""
    check: str = ""


class QuestionMapping(BaseModel):
    """How the user's words were resolved onto the platform — surfaced so the
    reader can see, and correct, what the copilot thought they meant."""

    intent: str | None = None
    services: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    metric_type: str | None = None
    window: str | None = None
    terms: list[str] = Field(default_factory=list)


class ReasoningObject(BaseModel):
    claim: str
    category: ReasoningCategory
    confidence: Confidence = Confidence.MEDIUM
    evidence: list[str] = Field(default_factory=list)  # evidence catalog ids


class Hypothesis(BaseModel):
    statement: str
    confidence: Confidence = Confidence.MEDIUM
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    status: str = "active"  # "active" | "retired"


class Investigation(BaseModel):
    """The structured result of one reasoning pass. Maps onto the Workspace
    sections and is the substrate every artifact is generated from."""

    question: str | None = None
    #: One quantitative sentence. Leads the chat reply.
    summary: str = ""
    #: The descriptive read, for the Workspace panel. Prose belongs here, not in
    #: the chat reply, so the two surfaces can differ in depth without differing
    #: in facts.
    narrative: str = ""
    facts: list[ReasoningObject] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommendations: list[ReasoningObject] = Field(default_factory=list)
    unknowns: list[ReasoningObject] = Field(default_factory=list)
    timeline: list[TelemetryEvent] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    #: Deterministic, not model-authored (see CoverageGap).
    gaps: list[CoverageGap] = Field(default_factory=list)
    mapping: QuestionMapping | None = None
