# Datadog Observability Copilot

An AI-powered **Observability Copilot** — an intelligent reasoning layer that turns
monitoring dashboards into guided, evidence-backed investigations. It explains system
health, reconstructs incident timelines, reasons about root causes (distinguishing
**Facts / Hypotheses / Recommendations / Unknowns** with traceable confidence), adapts
its explanation to your role, and generates operational artifacts — all backed by a
living, persisted **Investigation Workspace**.

This is **Iteration 0**: a coherent, runnable slice that proves the concept and is
architected for extension. It runs entirely on your machine.

---

## What you need first

- **Python 3.14** installed. To check, type this in your terminal and press Enter:
  ```bash
  python3 --version
  ```
  You should see `Python 3.14.x`. If not, install Python 3.14 before continuing.
- An **Anthropic API key** (for the reasoning) — get one at
  <https://console.anthropic.com/> → *Settings → API Keys*. You'll paste it in Step 4.
  The app still **starts** without it; the chat just tells you it isn't configured yet.

> Every command below is meant to be **copy-pasted into your terminal**, one block at a
> time, from the project folder. No coding required.

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

### 4. Add your Anthropic API key
Create your private settings file from the template (this `.env` file is **never**
committed to git):
```bash
cp .env.example .env
```
Now open `.env` in any text editor and put your key after the `=` on the
`ANTHROPIC_API_KEY` line, so it reads:
```
ANTHROPIC_API_KEY=sk-ant-...your key...
```
Save and close the file. Leave everything else as-is to use the built-in demo incident.

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

1. **Ask about the incident.** Type something like
   *“Is the system healthy right now? What changed?”* and send it. The Copilot reasons
   over the telemetry and replies with an evidence-backed narrative.
2. **See the evidence.** Under any reply, click **“Show me the evidence”** to expand the
   underlying signals behind the conclusion.
3. **Switch persona.** Change **“Explain as”** (top right) between *Support Engineer*,
   *SRE*, *Software Engineer*, *Product Manager*, *Engineering Leadership*. The **same
   facts** are re-framed for that audience — no new analysis is run.
4. **Generate an artifact.** Click **“Generate Incident Summary”** to produce a
   structured, copy-pasteable incident write-up built from the same investigation.

The canonical built-in scenario is a **deployment-induced latency incident**: a 09:02
deploy → cache hit-ratio drop → database latency rise → API SLO breach → support
tickets → rollback → recovery. It replays identically every time, so the demo is
reliable — but the AI's reasoning over it is genuine, never hard-coded.

---

## Running the tests (optional)

The project is built test-first. To run the full suite (no API key needed — the LLM is
faked in tests, so this costs nothing and never hits the network):
```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
You should see all tests passing.

---

## Optional: connect live Datadog (read-only)

To point the Copilot at a real Datadog org instead of the replayed incident, add these
to your `.env` and restart the app:
```
COPILOT_DATA_SOURCE=datadog
DATADOG_API_KEY=...your API key...
DATADOG_APP_KEY=...your Application key...
DATADOG_SITE=datadoghq.com
```
Keys come from your Datadog *Organization Settings* (API Keys / Application Keys). The
adapter is **read-only**. Leave `COPILOT_DATA_SOURCE=replay` for the reliable demo.

---

## How it's organized

```
app/
  config.py            Settings + secret loading (.env). Secrets never touch git or the DB.
  main.py              FastAPI app: serves the UI, /api/chat, /api/artifact, /api/status.
  copilot.py           CopilotSession: joins data + reasoning + workspace into the chat loop.
  personas.py          Registry of the 5 personas (config only) + deterministic rendering.
  artifacts.py         Registry of operational artifacts (Incident Summary).
  telemetry/           DataSource interface + ReplayAdapter (demo) and LiveDatadogAdapter.
  reasoning/           The Claude reasoning engine: structured objects, timeline, evidence.
  workspace/           The Investigation Workspace: SQLite append-with-history + sections.
  web/                 The browser UI (static HTML/CSS/JS).
tests/                 The full test suite.
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
- **The chat says Claude isn't configured** — your `ANTHROPIC_API_KEY` is missing or
  empty in `.env`. Add it (Step 4) and restart the app (Ctrl + C, then Step 5).
- **`Address already in use`** — something is already on port 8000. Start on another
  port, e.g. `python -m uvicorn app.main:app --port 8001`, and open
  `http://127.0.0.1:8001`.
- **Your prompt doesn't show `(.venv)`** — re-run `source .venv/bin/activate` from the
  project folder.
