# Presentation — two decks, pick one

Both cover the same material and the same 20–30 minute slot. They differ only in
**what leads**, because kickoff §7 defines two objectives and the ordering decides
which one the room hears first.

| | [`meta-led.html`](meta-led.html) | [`product-led.html`](product-led.html) |
|---|---|---|
| **Leads with** | the method — how a non-developer directed AI | the capability — what the tool does |
| **Product demo** | slide 4, one block (~5 min) | slides 4–6, three blocks (~6 min) |
| **Build journey** | slides 5–14, the bulk of the talk | slides 10–15, the closing act |
| **Pivot line** | — (method is the frame throughout) | slide 10: *"None of this was written by an engineer"* |
| **Follows kickoff** | §7.2 + §7.3 (*"the process is the message"*) | §7.1 first, then §7.2 |
| **Choose it when** | the audience is being shown *a way of working* | the audience needs to believe the tool first |
| **Risk** | product feels thin if the demo wobbles | you run out of time before the real point |

Both are 16 slides and share `deck.css`, `deck.js` and `charts.js` — edit a chart
once and both decks update.

**Recommendation:** `meta-led.html`. Kickoff §7.2 says the build journey is the
objective that matters most, and §7.3 makes the product the *evidence* for it.
`product-led.html` exists because that ordering is a judgement call about your
audience, not a fact — and because a room that doubts the tool won't listen to the
method.

## Running a deck

Just open the file — no server, no build step, no dependencies:

```
open docs/presentation/meta-led.html
```

| Key | Does |
|---|---|
| `→` `space` `PgDn` | next slide |
| `←` `PgUp` | previous |
| `N` | **speaker notes** — every slide has them |
| `F` | fullscreen |
| `Home` / `End` | first / last |
| digits then `Enter` | jump to slide number |

The slide number lives in the URL (`…#7`), so a mid-talk reload keeps your place.
**To export a PDF:** print to PDF from the browser — a print stylesheet lays every
slide out on its own page in light colours.

## Before you present

1. **Start the app** and leave it running in another window, on live Datadog:
   ```
   source .venv/bin/activate
   python -m uvicorn app.main:app --port 8000
   ```
2. **Confirm it's live, not replay:** `curl -s localhost:8000/api/status` should show
   `"data_source":"datadog"`. Also `python scripts/check_env.py`.
3. **Warm it up.** Ask one question before the room arrives — the first call is the
   slowest, and you'll see immediately whether the network and credential are healthy.
4. **Have a fallback.** If Datadog or the VPN fails, set `COPILOT_DATA_SOURCE=replay`
   and restart: the scripted incident always works. Say out loud that you've switched —
   the honesty costs nothing and the recovery is itself on-message.
5. **Questions that are known to work well** are listed in the speaker notes on the
   demo slides. The strongest is *"Is the alerting service healthy? Any errors or
   latency issues?"* — latency is the deepest seam in our telemetry (195 of 420 metrics).

⚠️ **Don't narrow the time window in the demo.** These metrics are sparse (~40–150
points per *week*), so a short window returns empty evidence. The 7-day default is
what makes it work.

## Where the numbers come from

Every figure on the slides traces to something in this repo — nothing is estimated:

| Claim | Source |
|---|---|
| 64 prompts · 7 active days · $207 · 24 planning / 40 implementation | `metrics/prompts.jsonl`, written automatically by the `Stop` hook in `.claude/settings.json`; aggregated by `metrics/analytics.py` |
| 388 tests · 98% coverage · the growth curve | `docs/context/TESTING.md` and `pytest --cov=app` |
| 23 decisions · 20 build-log entries | `docs/context/DECISIONS.md`, `BUILD-LOG.md` |
| 420 metrics · 14 services · 8 per question | verified live, `scripts/datadog_probe.py`; see `docs/context/STATE.md` |
| The failure stories | `docs/context/BUILD-LOG.md` (2026-07-03, 2026-07-08, 2026-08-05) |

Two numbers are deliberately **not** used, because they'd mislead: the collector's
`total_tokens` (~436M) is inflated by prompt-cache reads, and its
`peak_tests_passing` (297) is stale against today's 388. If someone asks about token
volume, the honest figure is **2.55M output tokens**.

Two honesty notes that are already written into the speaker notes, worth keeping
straight if you're challenged:

- **"7 active days"** means days on which work happened, spread over about six weeks
  of evenings — not seven full-time days.
- **The prompt count stops at 2026-07-28.** The final session (the live-Datadog work)
  isn't in `prompts.jsonl` yet, so 64 is a floor, not a total.

## Charts

`charts.js` holds three static inline SVG figures, shared by both decks. Form follows
the data's job rather than taste: single-hue column chart for per-day magnitude,
single-series line for the test-count trend (no legend — the title names the series),
and a horizontal stacked bar for the planning/implementation ratio rather than a
two-slice pie. Every mark carries a direct label and a `<title>`, so no value is
encoded by colour alone.

The two-colour palette is the validated dark-mode categorical pair (`#3987e5`,
`#d95926` on `#1a1a19`), run through the six palette checks rather than eyeballed:
normal-vision ΔE 31.8 (floor 15), CVD ΔE 26.8 under protanopia (target 8), contrast
4.79:1 and 4.48:1 against the surface (minimum 3.0).

To regenerate after new build activity, re-run the aggregation in `metrics/analytics.py`
and update the arrays at the top of the generator described in
`docs/context/BUILD-LOG.md` — the figures are static on purpose, since the numbers
are historical facts.
