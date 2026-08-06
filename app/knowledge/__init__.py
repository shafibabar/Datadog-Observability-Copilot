"""EC domain knowledge — the NLP layer between user words and real telemetry.

Five curated JSON files (see `data/`) describe how people actually talk about
the Enterprise Conduct surveillance platform: which everyday words name which
service, which lifecycle stage a service sits in, which metric family answers
"how slow" versus "how many", and — importantly — where the platform has NO
alert coverage at all.

The layer is deliberately:
  - **pure and offline** — no LLM call, no network, stdlib `json` only, so a
    question always resolves the same way and every rule is testable;
  - **tolerant** — a missing or malformed file degrades to an empty knowledge
    base rather than breaking startup (same contract as `build_monitors_index`);
  - **a hint layer, never an authority** — these files may PROPOSE metrics, but
    the live registry decides what exists. Parts of them are self-declared
    "inferred"/"not source-verified", and the org's own Terraform repo carries
    137 metrics that no longer emit. A metric that cannot return data must never
    be citable as evidence, so every proposal is intersected with what the data
    source can actually query.
"""
