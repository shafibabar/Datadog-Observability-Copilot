const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const personaSel = document.getElementById("persona");
const banner = document.getElementById("status-banner");

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return bubble;
}

// "Show me the evidence" — a first-class, always-available disclosure attached
// to any reply that carries evidence pointers.
function attachEvidence(bubble, evidence) {
  if (!evidence || !evidence.length) return;
  const details = document.createElement("details");
  details.className = "evidence";
  const summary = document.createElement("summary");
  summary.textContent = `Show me the evidence (${evidence.length})`;
  details.appendChild(summary);
  const list = document.createElement("ul");
  for (const e of evidence) {
    const li = document.createElement("li");
    li.textContent = `[${e.kind}] ${e.ref} — ${e.detail}`;
    list.appendChild(li);
  }
  details.appendChild(list);
  bubble.appendChild(details);
}

function renderReply(bubble, data) {
  bubble.textContent = data.reply ?? "(no reply)";
  attachEvidence(bubble, data.evidence);
  chat.scrollTop = chat.scrollHeight;
}

async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    const parts = [`source: ${s.data_source}`];
    parts.push(s.anthropic_configured ? "Claude ✓" : "Claude ✗");
    if (s.data_source === "datadog") parts.push(s.datadog_configured ? "Datadog ✓" : "Datadog ✗");
    banner.textContent = parts.join("  ·  ");
    banner.className = "status " + (s.anthropic_configured ? "ok" : "warn");
  } catch {
    banner.textContent = "status unavailable";
    banner.className = "status warn";
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  addMessage("user", message);
  input.value = "";
  sendBtn.disabled = true;
  const thinking = addMessage("assistant", "…");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, persona: personaSel.value }),
    });
    const data = await r.json();
    renderReply(thinking, data);
  } catch {
    thinking.textContent = "Something went wrong reaching the backend.";
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
});

// Generate the Incident Summary artifact — a transform over the current
// investigation state, rendered as markdown into the conversation.
const genSummaryBtn = document.getElementById("gen-summary");
genSummaryBtn.addEventListener("click", async () => {
  const bubble = addMessage("assistant", "Generating Incident Summary…");
  try {
    const r = await fetch("/api/artifact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: "incident_summary" }),
    });
    const data = await r.json();
    bubble.textContent = data.markdown ?? data.error ?? "(no artifact)";
    chat.scrollTop = chat.scrollHeight;
  } catch {
    bubble.textContent = "Something went wrong generating the artifact.";
  }
});

// Switching persona re-frames the existing investigation (same facts, new lens)
// via an empty-message re-render — no new reasoning pass.
personaSel.addEventListener("change", async () => {
  const bubble = addMessage("assistant", "…");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "", persona: personaSel.value }),
    });
    renderReply(bubble, await r.json());
  } catch {
    bubble.textContent = "Something went wrong reaching the backend.";
  }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

refreshStatus();
