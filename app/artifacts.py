"""Operational artifacts (kickoff §5.10).

An artifact is a *transform over the Workspace/Investigation state* — it reshapes
existing findings for a specific audience and invents nothing. The set is
registry-driven (append an `ArtifactSpec` to add a new type) so future artifacts
(Executive Briefing, Customer Communication Draft, Post-Incident Report,
Runbook Recommendation — the last confidence-gated) drop in without touching the
reasoning layer. Iteration 0 ships the Incident Summary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from app.reasoning.models import Confidence, Investigation
from app.telemetry.models import Severity

_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
_SEVERITY_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


class ArtifactSection(BaseModel):
    heading: str
    body: str


class ArtifactDocument(BaseModel):
    key: str
    title: str
    audience: str
    sections: list[ArtifactSection]

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""]
        for s in self.sections:
            lines.append(f"## {s.heading}")
            lines.append(s.body)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class ArtifactSpec:
    key: str
    label: str
    audience: str
    build: Callable[[Investigation, str], ArtifactDocument]


# --- helpers ---------------------------------------------------------------

def _peak_severity(inv: Investigation) -> Severity:
    if not inv.timeline:
        return Severity.INFO
    return max((e.severity for e in inv.timeline), key=lambda s: _SEVERITY_RANK[s])


def _top_hypothesis(inv: Investigation):
    active = [h for h in inv.hypotheses if h.status == "active"]
    if not active:
        return None
    return max(active, key=lambda h: _CONFIDENCE_RANK[h.confidence])


# --- Incident Summary ------------------------------------------------------

def _build_incident_summary(inv: Investigation, incident_id: str) -> ArtifactDocument:
    sections: list[ArtifactSection] = []

    sections.append(ArtifactSection(
        heading="Summary",
        body=inv.summary or "No summary available yet.",
    ))

    sev = _peak_severity(inv)
    sections.append(ArtifactSection(
        heading="Severity",
        body=f"Peak observed severity: {sev.value}.",
    ))

    if inv.timeline:
        timeline = "\n".join(
            f"- {e.timestamp:%H:%M} — {e.title}"
            + (f" ({e.severity.value})" if e.severity != Severity.INFO else "")
            for e in inv.timeline
        )
    else:
        timeline = "No timeline events recorded."
    sections.append(ArtifactSection(heading="Timeline", body=timeline))

    top = _top_hypothesis(inv)
    if top is not None:
        cause = f"{top.statement} (confidence: {top.confidence.value})"
        if top.missing_information:
            cause += "\n\nStill missing: " + ", ".join(top.missing_information)
    else:
        cause = "No root-cause hypothesis has been established yet."
    sections.append(ArtifactSection(heading="Likely Cause", body=cause))

    if inv.recommendations:
        recs = "\n".join(f"- {r.claim}" for r in inv.recommendations)
    else:
        recs = "No recommended actions yet."
    sections.append(ArtifactSection(heading="Recommended Next Steps", body=recs))

    # Outstanding questions = declared unknowns + each hypothesis's missing info.
    questions = [u.claim for u in inv.unknowns]
    for h in inv.hypotheses:
        questions.extend(h.missing_information)
    if questions:
        sections.append(ArtifactSection(
            heading="Outstanding Questions",
            body="\n".join(f"- {q}" for q in questions),
        ))

    return ArtifactDocument(
        key="incident_summary",
        title=f"Incident Summary — {incident_id}",
        audience="Incident-response team",
        sections=sections,
    )


REGISTRY: dict[str, ArtifactSpec] = {
    "incident_summary": ArtifactSpec(
        key="incident_summary",
        label="Incident Summary",
        audience="Incident-response team",
        build=_build_incident_summary,
    ),
}


def render_artifact(
    key: str, investigation: Investigation, incident_id: str = "incident"
) -> ArtifactDocument:
    """Render one artifact from the current investigation state.

    Raises KeyError if the artifact type is not registered."""
    spec = REGISTRY[key]
    return spec.build(investigation, incident_id)
