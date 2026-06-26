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


class Evidence(BaseModel):
    """A pointer from a claim down to the underlying telemetry."""

    id: str            # catalog id, e.g. "evt:e1" or "met:api.latency.p95"
    kind: str          # "event" | "metric"
    ref: str           # the event id or metric name
    detail: str        # human-readable, drillable description


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
    summary: str = ""
    facts: list[ReasoningObject] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommendations: list[ReasoningObject] = Field(default_factory=list)
    unknowns: list[ReasoningObject] = Field(default_factory=list)
    timeline: list[TelemetryEvent] = Field(default_factory=list)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
