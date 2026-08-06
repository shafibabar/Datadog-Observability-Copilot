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


#: Every persona surfaces `coverage_gaps`. It stays registry config rather than
#: a hard-coded append in render(), but it is present in all five deliberately:
#: "no monitor exists for this" is a fact a lens may re-frame, never drop.
REGISTRY: dict[str, Persona] = {
    "support": Persona(
        "support", "Support Engineer",
        ["customer_impact", "current_health", "coverage_gaps",
         "recommended_next_steps"],
        detail="low", vocabulary="plain",
    ),
    "sre": Persona(
        "sre", "Site Reliability Engineer",
        ["current_health", "timeline", "root_cause", "coverage_gaps",
         "recommended_next_steps", "metrics_queried", "confidence"],
        detail="high", vocabulary="technical",
    ),
    "swe": Persona(
        "swe", "Software Engineer",
        ["timeline", "root_cause", "affected_services", "coverage_gaps",
         "recommended_next_steps", "metrics_queried"],
        detail="high", vocabulary="technical",
    ),
    "pm": Persona(
        "pm", "Product Manager",
        ["customer_impact", "current_health", "coverage_gaps",
         "recommended_next_steps"],
        detail="low", vocabulary="plain",
    ),
    "leadership": Persona(
        "leadership", "Engineering Leadership",
        ["customer_impact", "current_health", "coverage_gaps",
         "recommended_next_steps", "confidence"],
        detail="low", vocabulary="plain",
    ),
}

_DEFAULT = "sre"


def get_persona(key: str | None) -> Persona:
    return REGISTRY.get((key or "").lower(), REGISTRY[_DEFAULT])


# --- value formatting -------------------------------------------------------

def _num(value: float | None) -> str:
    """Thousands-separated, and integral values without a trailing ".0" — a
    reply is read at a glance, so 1,840 beats 1840.0."""
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _chip(confidence) -> str:
    """Confidence as a bracket token. The reply is persisted and copied as plain
    text, so the marker has to survive as text; the UI turns it into a coloured
    chip at render time (see renderMarkdown in app/web/static/app.js)."""
    value = getattr(confidence, "value", confidence)
    return f"  [{value}]" if value else ""


def _measurement(ev) -> str:
    """One metric's numbers, in the order a reader wants them: what it is now,
    what it was, and how far it moved."""
    if not ev.has_data:
        return f"{ev.ref} — no data returned in the selected window"

    unit = f" {ev.unit}" if ev.unit else ""
    parts = []
    if ev.latest is not None:
        parts.append(f"latest {_num(ev.latest)}{unit}")
    if ev.baseline is not None:
        parts.append(f"baseline {_num(ev.baseline)}")
    if ev.extreme is not None and ev.extreme != ev.baseline:
        parts.append(f"peak {_num(ev.extreme)}")
    if ev.points:
        parts.append(f"{ev.points:,} pts")
    return f"{ev.ref} — " + " · ".join(parts) if parts else ev.ref


def _attribution(ev) -> str:
    """Where the number came from — the "which phase/stage/service" question."""
    bits = [b for b in (
        f"stage {ev.stage}" if ev.stage else "",
        ev.service or "",
    ) if b]
    return " · ".join(bits)


def _evidence_lines(claim_evidence, inv, detail) -> list[str]:
    """The measurement behind a claim, indented under it. This is the whole
    point of the reply: a claim without its number is an opinion."""
    lines = []
    for eid in claim_evidence or []:
        ev = inv.evidence.get(eid)
        if ev is None or ev.kind != "metric":
            continue
        lines.append(f"  {_measurement(ev)}")
        where = _attribution(ev)
        if where:
            lines.append(f"  {where}")
    return lines


# --- section formatters (content -> lines), lens applied via persona.detail --

def _fmt_current_health(content, detail, inv) -> list[str]:
    lines = []
    for f in content:  # facts
        lines.append(f"- {f.claim}{_chip(f.confidence)}")
        lines.extend(_evidence_lines(f.evidence, inv, detail))
    return lines


def _fmt_timeline(content, detail, inv) -> list[str]:
    if detail != "high":
        return []  # timeline detail is for technical personas
    return [f"- {evt.timestamp:%H:%M} — {evt.title}" for evt in content]


def _fmt_root_cause(content, detail, inv) -> list[str]:
    lines = []
    for h in content:  # hypotheses
        lines.append(f"- {h.statement}{_chip(h.confidence)}")
        lines.extend(_evidence_lines(h.supporting_evidence, inv, detail))
        if detail == "high":
            if h.supporting_evidence:
                lines.append(f"    for: {', '.join(h.supporting_evidence)}")
            if h.contradicting_evidence:
                lines.append(f"    against: {', '.join(h.contradicting_evidence)}")
            if h.missing_information:
                lines.append(f"    missing: {', '.join(h.missing_information)}")
    return lines


def _fmt_recommended_next_steps(content, detail, inv) -> list[str]:
    return [f"- {r.claim}{_chip(r.confidence)}" for r in content]


def _fmt_customer_impact(content, detail, inv) -> list[str]:
    # content = support-sourced timeline events
    return [f"- {evt.timestamp:%H:%M} — {evt.title}" for evt in content]


def _fmt_affected_services(content, detail, inv) -> list[str]:
    return [f"- {s}" for s in content] if content else []


def _fmt_confidence(content, detail, inv) -> list[str]:
    # content = {hypothesis statement: Confidence}
    return [f"- {stmt}{_chip(conf)}" for stmt, conf in content.items()]


def _fmt_coverage_gaps(content, detail, inv) -> list[str]:
    """Shown to EVERY persona. A missing monitor is precisely what a
    non-technical reader would otherwise read as health."""
    lines = []
    for gap in content:
        topic = gap.topic.replace("_", " ")
        lines.append(f"- {topic} — {gap.reason}" if gap.reason else f"- {topic}")
        if gap.check:
            lines.append(f"  check: {gap.check}")
    return lines


def _fmt_metrics_queried(content, detail, inv) -> list[str]:
    """The audit trail: exactly which series this answer was derived from.
    Technical personas only — it is provenance, not narrative."""
    if detail != "high":
        return []
    lines = []
    for ev in content:
        state = f"{ev.points:,} pts" if ev.has_data else "no data"
        lines.append(f"- {ev.ref} — {state}")
    return lines


_FORMATTERS = {
    "current_health": _fmt_current_health,
    "timeline": _fmt_timeline,
    "root_cause": _fmt_root_cause,
    "recommended_next_steps": _fmt_recommended_next_steps,
    "customer_impact": _fmt_customer_impact,
    "affected_services": _fmt_affected_services,
    "confidence": _fmt_confidence,
    "coverage_gaps": _fmt_coverage_gaps,
    "metrics_queried": _fmt_metrics_queried,
}

_HEADINGS = {
    "current_health": "Current health",
    "timeline": "Timeline",
    "root_cause": "Likely cause",
    "recommended_next_steps": "Recommended next steps",
    "customer_impact": "Customer impact",
    "affected_services": "Affected services",
    "confidence": "Confidence",
    "coverage_gaps": "Not available",
    "metrics_queried": "Metrics queried",
}


def render(persona: Persona, investigation: Investigation) -> str:
    """Compose a persona-adapted reply from the Investigation.

    The one-line quantitative headline leads; the persona then surfaces its
    concern sections at its detail level, each claim carrying the measurement it
    rests on. The long descriptive prose deliberately does NOT appear here — it
    lives in `narrative`, which the Workspace panel renders — so the chat stays
    scannable while the panel stays readable. Same facts, two depths.
    """
    views = {v.key: v for v in render_sections(investigation)}
    blocks: list[str] = []

    if investigation.summary:
        blocks.append(investigation.summary)

    for key in persona.lead_sections:
        formatter = _FORMATTERS.get(key)
        view = views.get(key)
        if formatter is None or view is None:
            continue
        lines = formatter(view.content, persona.detail, investigation)
        if lines:
            blocks.append(f"{_HEADINGS[key]}:\n" + "\n".join(lines))

    return "\n\n".join(blocks)
