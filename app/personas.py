"""Persona registry + deterministic rendering (kickoff §5.1).

A persona is *config*: which Workspace sections to surface first, the vocabulary
level, and the detail depth. It is an input to the rendering layer only — it
never alters the underlying facts or evidence. Rendering composes the reply from
the structured Investigation (via the section registry), so it is deterministic,
grounded, cheap (no extra LLM call), and fully testable. New personas are added
by appending to REGISTRY — no change to core reasoning.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.reasoning.models import Investigation
from app.workspace.sections import render_sections


@dataclass(frozen=True)
class Persona:
    key: str
    label: str
    lead_sections: list[str]  # section keys to surface first
    detail: str               # "low" | "medium" | "high"
    vocabulary: str           # "plain" | "technical"


REGISTRY: dict[str, Persona] = {
    "support": Persona(
        "support", "Support Engineer",
        ["customer_impact", "current_health", "recommended_next_steps"],
        detail="low", vocabulary="plain",
    ),
    "sre": Persona(
        "sre", "Site Reliability Engineer",
        ["current_health", "timeline", "root_cause", "recommended_next_steps", "confidence"],
        detail="high", vocabulary="technical",
    ),
    "swe": Persona(
        "swe", "Software Engineer",
        ["timeline", "root_cause", "affected_services", "recommended_next_steps"],
        detail="high", vocabulary="technical",
    ),
    "pm": Persona(
        "pm", "Product Manager",
        ["customer_impact", "recommended_next_steps"],
        detail="low", vocabulary="plain",
    ),
    "leadership": Persona(
        "leadership", "Engineering Leadership",
        ["customer_impact", "recommended_next_steps", "confidence"],
        detail="low", vocabulary="plain",
    ),
}

_DEFAULT = "sre"


def get_persona(key: str | None) -> Persona:
    return REGISTRY.get((key or "").lower(), REGISTRY[_DEFAULT])


# --- section formatters (content -> lines), lens applied via persona.detail --

def _fmt_current_health(content, detail) -> list[str]:
    lines = []
    for f in content:  # facts
        suffix = f"  (confidence: {f.confidence.value})" if detail == "high" else ""
        lines.append(f"- {f.claim}{suffix}")
    return lines


def _fmt_timeline(content, detail) -> list[str]:
    events = content
    if detail != "high":
        return []  # timeline detail is for technical personas
    lines = []
    for evt in events:
        lines.append(f"- {evt.timestamp:%H:%M} — {evt.title}")
    return lines


def _fmt_root_cause(content, detail) -> list[str]:
    lines = []
    for h in content:  # hypotheses
        lines.append(f"- {h.statement} (confidence: {h.confidence.value})")
        if detail == "high":
            if h.supporting_evidence:
                lines.append(f"    for: {', '.join(h.supporting_evidence)}")
            if h.contradicting_evidence:
                lines.append(f"    against: {', '.join(h.contradicting_evidence)}")
            if h.missing_information:
                lines.append(f"    missing: {', '.join(h.missing_information)}")
    return lines


def _fmt_recommended_next_steps(content, detail) -> list[str]:
    return [f"- {r.claim}" for r in content]


def _fmt_customer_impact(content, detail) -> list[str]:
    # content = support-sourced timeline events
    return [f"- {evt.timestamp:%H:%M} — {evt.title}" for evt in content]


def _fmt_affected_services(content, detail) -> list[str]:
    return [f"- {s}" for s in content] if content else []


def _fmt_confidence(content, detail) -> list[str]:
    # content = {hypothesis statement: Confidence}
    return [f"- {stmt}: {conf.value}" for stmt, conf in content.items()]


_FORMATTERS = {
    "current_health": _fmt_current_health,
    "timeline": _fmt_timeline,
    "root_cause": _fmt_root_cause,
    "recommended_next_steps": _fmt_recommended_next_steps,
    "customer_impact": _fmt_customer_impact,
    "affected_services": _fmt_affected_services,
    "confidence": _fmt_confidence,
}

_HEADINGS = {
    "current_health": "Current health",
    "timeline": "Timeline",
    "root_cause": "Likely cause",
    "recommended_next_steps": "Recommended next steps",
    "customer_impact": "Customer impact",
    "affected_services": "Affected services",
    "confidence": "Confidence",
}


def render(persona: Persona, investigation: Investigation) -> str:
    """Compose a persona-adapted reply from the Investigation. The summary always
    leads (the narrative); the persona then surfaces its concern sections at its
    detail level. Same facts, different lens."""
    views = {v.key: v for v in render_sections(investigation)}
    blocks: list[str] = []

    if investigation.summary:
        blocks.append(investigation.summary)

    for key in persona.lead_sections:
        formatter = _FORMATTERS.get(key)
        view = views.get(key)
        if formatter is None or view is None:
            continue
        lines = formatter(view.content, persona.detail)
        if lines:
            blocks.append(f"{_HEADINGS[key]}:\n" + "\n".join(lines))

    return "\n\n".join(blocks)
