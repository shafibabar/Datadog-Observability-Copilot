# Datadog Observability Copilot

An AI-powered **Observability Copilot** — an intelligent reasoning layer that turns
monitoring dashboards into guided, evidence-backed investigations. It explains system
health, reconstructs incident timelines, reasons about root causes (distinguishing
**Facts / Hypotheses / Recommendations / Unknowns** with traceable confidence), adapts
its explanation to your role, and generates operational artifacts — all backed by a
living, persisted **Investigation Workspace**.

A coherent, runnable slice that proves the concept and is architected for extension —
it runs entirely on your machine. Recent iterations added a keyless **Claude Code CLI**
backend, a pre-reasoning **relevance & abuse guard**, and **scoped investigations**: you
pick the **Environment**, **Tenant**, **time window**, and explanation **persona** from a
single scope menu under the prompt, and the reasoning is confined to that slice.

---

## What you need first

- **Python 3.14** installed. To check, type this in your terminal and press Enter:
  ```bash
  python3 --version
  ```
  You should see `Python 3.14.x`. If not, install Python 3.14 before continuing.
- **A way for the app to reach Claude** (for the reasoning). You need **one** of
  these — see [Connect Claude](#connect-claude-choose-one) below for how to get each:
  - **The Claude Code CLI, signed in** — *no API key needed*. If you already use
    Claude Code, you're set; this is the default.
  - **An Anthropic API key** — if you'd rather use the API directly.

  The app still **starts** without either; the chat just tells you it isn't
  configured yet.

> Every command below is meant to be **copy-pasted into your terminal**, one block at a
> time, from the project folder. No coding required.

---

## Connect Claude (choose one)

The reasoning layer needs to talk to Claude. Pick **whichever you already have** — you
do **not** need both. The app auto-detects: if no API key is set, it uses the Claude Code
CLI; if a key is set, it uses the API. (You can force the choice with `COPILOT_LLM_BACKEND`
in `.env`: `auto` / `cli` / `sdk`.)

### Option A — the Claude Code CLI (no API key) · *recommended if you use Claude Code*
The app runs Claude through your **local Claude Code sign-in** — nothing to paste into
`.env`. You just need the `claude` CLI installed and logged in.

**How to obtain it:**
1. If you don't have it yet, install the CLI:
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
2. Sign in once (this opens your browser to authenticate; it remembers you afterward):
   ```bash
   claude
   ```
   Follow the prompt to log in, then type `/exit` to leave the chat. To verify you're
   signed in, run `claude -p "say ok"` — you should see `ok`.

That's the whole setup — leave `ANTHROPIC_API_KEY` blank in `.env`.

### Option B — an Anthropic API key
Use the Anthropic API directly instead of the CLI.

**How to obtain it:** go to <https://console.anthropic.com/> → *Settings → API Keys* →
**Create Key**, copy it (starts with `sk-ant-`), and paste it into `.env` on the
`ANTHROPIC_API_KEY=` line (Step 4). Note: API usage is billed to that Anthropic account.

---

## Run it — step by step

### 1. Go to the project folder
```bash
cd /home/shafi/Datadog-Observability-Copilot
```

### 2. Create an isolated environment (one time)
This keeps the project's libraries separate from the rest of your system.
```bash
python3 -m venv .venv
```

### 3. Activate the environment and install the libraries
You must run the **activate** line every time you open a new terminal to work on this
project. (You'll know it worked when your prompt shows `(.venv)`.)
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Create your settings file and connect Claude
Create your private settings file from the template (this `.env` file is **never**
committed to git):
```bash
cp .env.example .env
```
Now connect Claude. See [Connect Claude](#connect-claude-choose-one) just below for the
two options and how to obtain each.

- **Using the Claude Code CLI (default, no key):** you don't need to edit `.env` at all —
  just make sure you're signed in to Claude Code (see [Option A](#option-a--the-claude-code-cli-no-api-key--recommended-if-you-use-claude-code)).
  Leave everything as-is.
- **Using an Anthropic API key:** open `.env` in any text editor and put your key after
  the `=` on the `ANTHROPIC_API_KEY` line, so it reads
  `ANTHROPIC_API_KEY=sk-ant-...your key...`, then save.

Leave everything else as-is to use the built-in demo incident.

### 5. Start the app
```bash
python -m uvicorn app.main:app --port 8000
```
You'll see a line like `Uvicorn running on http://127.0.0.1:8000`. Leave this terminal
running. To stop the app later, press **Ctrl + C** in this terminal.

### 6. Open it in your browser
Go to:
```
http://127.0.0.1:8000
```

That's it — you're running the Copilot.

---

## Walk the demo

With the app open in your browser:

1. **Set the scope.** Below the prompt is a **Scope** button. Click it and drill into
   **Environment** and **Tenant** (pick one or more of each), **Duration** (presets like
   *Last 1 hour*, or a **Custom range** — capped at 7 days, within the last 2 years, no
   future dates), and **Explain as** (the persona). On the built-in demo these come
   pre-populated (`production`/`staging`, a few tenants); on live Datadog they're pulled
   from your org. At least one Environment or Tenant is required before you can send.
2. **Ask about the incident.** Type something like
   *“Is the system healthy right now? What changed?”* and send it. The Copilot reasons
   over the telemetry **within your scope** and replies with an evidence-backed narrative.
3. **See the evidence.** Under any reply, click **“Show me the evidence”** to expand the
   underlying signals behind the conclusion. Each reply also has a **Copy** button.
4. **Switch persona anytime.** Reopen **Scope → Explain as** and choose *Support Engineer*,
   *SRE*, *Software Engineer*, *Product Manager*, or *Engineering Leadership*. The **same
   facts** are re-framed for that audience — no new analysis is run.
5. **Generate an artifact.** Click **“Incident Summary”** (top right) to produce a
   structured, copy-pasteable incident write-up built from the same investigation.
6. **Manage conversations.** The left sidebar lists investigations (each gets a subject
   from its summary); hover the **⋯** menu to rename or delete. Both side panels can be
   dragged to resize or collapsed with the chevron on their divider.

The canonical built-in scenario is a **deployment-induced latency incident**: a 09:02
deploy → cache hit-ratio drop → database latency rise → API SLO breach → support
tickets → rollback → recovery. It replays identically every time, so the demo is
reliable — but the AI's reasoning over it is genuine, never hard-coded.

---

## Running the tests (optional)

The project is built test-first. To run the full suite (no API key needed — the LLM is
faked and Datadog HTTP is mocked, so this costs nothing and never hits the network):
```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
You should see all tests passing (currently **243 passed, 1 skipped**). The suite covers
unit tests (models, guard, scope, adapters, store, personas, artifacts), functional API
tests via `TestClient`, and declarative **UI-contract** tests (`tests/test_web_ui.py`)
that assert the served markup/JS.

**Optional real-browser smoke test.** `tests/test_smoke_playwright.py` drives an actual
browser through the scope menu; it **skips** unless Playwright and a browser are installed
(so it never breaks the offline run). To enable it on a networked machine:
```bash
pip install playwright && playwright install chromium
pytest tests/test_smoke_playwright.py
```
(Playwright is intentionally not in `requirements-dev.txt` — it's an opt-in extra.)

---

## Run the metrics dashboard (the "vibe-coding" meta-story)

Alongside the product there's a small **metrics subsystem** (in `metrics/`) that tracks
how this project itself was built with Claude Code — prompts, tokens, cost, and
code-change velocity over time. It's a separate local app that runs just like the
product. **No API key and no extra install are needed** (it reuses the libraries from
Step 3 and a standalone, dependency-free collector).

### 1. Activate the environment (same as the product)
```bash
cd /home/shafi/Datadog-Observability-Copilot
source .venv/bin/activate
```

### 2. Start the metrics dashboard
```bash
python -m uvicorn metrics.dashboard:app --port 8055
```
Leave this terminal running (Ctrl + C to stop). You can run it **at the same time** as
the product app — they use different ports (8000 vs 8055).

### 3. Open it in your browser
```
http://127.0.0.1:8055
```
You'll see charts of prompts over time, token/cost totals, and code churn — rendered with
plain `<canvas>`, no external chart library.

**Where the data comes from:** each recorded session is one line in
`metrics/prompts.jsonl`. A Claude Code **`Stop` hook** (configured in
`.claude/settings.json`) runs `metrics/collector.py` automatically after each prompt and
appends a record — so the dashboard fills in as you keep working. Nothing to run by hand.

---

## Optional: connect live Datadog (read-only)

To point the Copilot at a real Datadog org instead of the replayed incident, add your
credential to `.env` and restart the app. The adapter is **read-only**. Leave
`COPILOT_DATA_SOURCE=replay` for the reliable demo.

### Recommended: a Personal Access Token (PAT)
Datadog now offers token-based auth. A **Personal Access Token** is a single,
self-contained credential (no separate application key needed):
```
COPILOT_DATA_SOURCE=datadog
DATADOG_ACCESS_TOKEN=...your token...
DATADOG_SITE=datadoghq.com
```

**How to obtain a PAT:** in Datadog, click your **avatar → Personal Settings → Access
Tokens → “+ New Access Token”**. Give it a name, choose an expiry (24 hours to 1 year),
click **Select Scopes** and grant read scopes (e.g. metrics/events read), then create it.
**Copy the token immediately — it's shown only once.** Paste it into
`DATADOG_ACCESS_TOKEN`. The app sends it as an `Authorization: Bearer` header.

### Legacy alternative: API key + Application key
The classic key pair still works (Datadog considers it legacy). Use it if that's what
your org has:
```
COPILOT_DATA_SOURCE=datadog
DATADOG_API_KEY=...your API key...
DATADOG_APP_KEY=...your Application key...
DATADOG_SITE=datadoghq.com
```
These come from your Datadog *Organization Settings* (API Keys / Application Keys). If a
PAT is also set, the PAT takes precedence.

> Set `DATADOG_SITE` to your region (`datadoghq.com`, `datadoghq.eu`, `us3.datadoghq.com`, …).

### Scope dropdowns (Environment / Tenant)
The scope menu populates its **Environment** and **Tenant** lists from your org. `env` is
Datadog's standard environment tag; **"tenant" is not a native Datadog concept**, so tell
the app which tag key represents it (your org may call it `tenant`, `customer`, `account`, …):
```
DATADOG_TENANT_TAG=tenant
DATADOG_DISCOVERY_METRIC=system.cpu.user
```
`DATADOG_DISCOVERY_METRIC` is a widely-emitted metric the app queries **only** to list the
distinct env/tenant tag values for the dropdowns — it must be a metric that actually carries
those tags in your org. If the dropdowns come up empty, point it at one that does.

> **Not yet validated live.** The live env/tenant discovery and scoped queries are currently
> tested only against mocked Datadog responses; the exact query/tag shapes should be confirmed
> against a real org (tracked in `docs/context/OPEN-QUESTIONS.md`).

### Confirm your configuration
Not sure whether the app is actually seeing your settings? Run the safe diagnostic (it
prints which keys are set — never their values — and what the app resolves):
```
python scripts/check_env.py
```

---

## How it's organized

```
app/
  config.py            Settings + secret loading (.env), incl. .env diagnostics. Secrets never touch git or the DB.
  main.py              FastAPI app: serves the UI (cache-busted), /api/conversations, /api/scopes, /api/status.
  copilot.py           Copilot: joins data + reasoning + workspace across conversations; per-conversation scope; guard.
  guard.py             Pre-reasoning relevance & abuse gate (blocks off-topic / injection before any spend).
  personas.py          Registry of the 5 personas (config only) + deterministic rendering.
  artifacts.py         Registry of operational artifacts (Incident Summary).
  telemetry/           DataSource interface + ReplayAdapter (demo) and LiveDatadogAdapter; Scope model + list_scopes discovery.
  reasoning/           Reasoning engine + the LLM seam: Claude via the CLI (no key) or the API SDK.
  workspace/           The Investigation Workspace: SQLite append-with-history + sections (+ per-conversation scope, delete).
  web/                 The browser UI (static HTML/CSS/JS): Claude-style theme + the scope menu.
metrics/               The build-metrics subsystem: collector (Stop hook) + local dashboard.
scripts/               check_env.py — safe .env / config diagnostic (no secret values printed).
tests/                 The full test suite (unit + functional + UI-contract; optional Playwright smoke).
docs/context/          Project memory: PROJECT, STATE, ROADMAP, DECISIONS, BUILD-LOG, etc.
```

The four layers — **telemetry**, **reasoning**, **investigation-state (Workspace)**, and
**presentation** — are deliberately separable, so a real backend, more personas, more
artifacts, and downstream integrations can be added without rewrites.

**New to the project?** Read `docs/context/PROJECT.md` and `docs/context/STATE.md` first —
they are the authoritative, version-controlled source of truth for where things stand.

---

## Troubleshooting

- **`python3: command not found`** — Python isn't installed or isn't on your PATH.
  Install Python 3.14.
- **The chat says Claude isn't configured** — neither backend is available. Either sign
  in to the Claude Code CLI ([Option A](#option-a--the-claude-code-cli-no-api-key--recommended-if-you-use-claude-code):
  run `claude` once and log in), or add an `ANTHROPIC_API_KEY` to `.env`
  ([Option B](#option-b--an-anthropic-api-key)). Then restart the app (Ctrl + C, then Step 5).
- **The chat errors mentioning the `claude` CLI** — you're on the CLI backend but the CLI
  isn't installed or signed in. Run `claude` and log in (Option A), or switch to an API
  key (Option B). Confirm with `claude -p "say ok"`.
- **`Address already in use`** — something is already on port 8000. Start on another
  port, e.g. `python -m uvicorn app.main:app --port 8001`, and open
  `http://127.0.0.1:8001`.
- **Your prompt doesn't show `(.venv)`** — re-run `source .venv/bin/activate` from the
  project folder.
- **The UI looks broken / mangled after an update** — your browser is likely showing a
  stale stylesheet. Hard-refresh: **Ctrl + Shift + R** (Windows/Linux) or
  **Cmd + Shift + R** (Mac). The app already versions its CSS/JS to prevent this, but a
  hard refresh clears anything cached from before.
- **The scope dropdowns are empty / it still says `replay` with Datadog set** — the app
  isn't resolving your Datadog config. Run `python scripts/check_env.py` to see exactly
  what's set and what's missing (it never prints secret values). Common causes: you edited
  `.env.example` instead of `.env`, `COPILOT_DATA_SOURCE` isn't `datadog`, the credential
  is blank, or `DATADOG_DISCOVERY_METRIC` doesn't carry your env/tenant tags. Restart after
  editing `.env`.
- **The Copilot declines an off-topic question** — that's the relevance guard. Ask about
  system health, telemetry, deploys, errors, or an incident and it will investigate.
