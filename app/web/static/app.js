"use strict";

// ---------- element refs ----------
const $ = (id) => document.getElementById(id);
const appEl = $("app");
const chat = $("chat");
const convoList = $("convo-list");
const convoTitle = $("convo-title");
const form = $("composer");
const input = $("input");
const sendBtn = $("send");
const personaSel = $("persona");
const banner = $("status-banner");
const newChatBtn = $("new-chat");
const genSummaryBtn = $("gen-summary");
const toggleWsBtn = $("toggle-workspace");
const wsBody = $("ws-body");
const wsSnapshot = $("ws-snapshot");

// ---------- state ----------
const state = { configured: false, currentId: null, conversations: [] };
const LAST_KEY = "copilot.lastConversation";

// ---------- helpers ----------
function escapeHtml(s) {
  return (s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Minimal, safe markdown: escape first, then apply a few block/inline rules.
function renderMarkdown(text) {
  const lines = (text || "").split("\n");
  let html = "";
  let inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^#{1,3}\s+(.*)$/))) {
      closeList();
      const level = line.match(/^#+/)[0].length;
      html += `<h${level}>${inline(m[1])}</h${level}>`;
    } else if ((m = line.match(/^[-*]\s+(.*)$/))) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(m[1])}</li>`;
    } else if (line === "") {
      closeList();
    } else {
      closeList();
      html += `<p>${inline(line)}</p>`;
    }
  }
  closeList();
  return html;

  function inline(s) {
    return escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }
}

function relativeTime(iso) {
  if (!iso) return "";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  return { ok: r.ok, status: r.status, data: await r.json().catch(() => ({})) };
}

// ---------- chat rendering ----------
function clearChat() { chat.innerHTML = ""; }

function addMessage(role, content, { markdown = false, tag = null, artifact = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble" + (artifact ? " artifact" : "");
  if (tag) {
    const t = document.createElement("span");
    t.className = "meta-tag";
    t.textContent = tag;
    bubble.appendChild(t);
  }
  const body = document.createElement("div");
  if (markdown) body.innerHTML = renderMarkdown(content);
  else body.textContent = content;
  bubble.appendChild(body);
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return bubble;
}

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
    li.innerHTML = `<span class="ev-kind">[${escapeHtml(e.kind)}]</span> ` +
      `${escapeHtml(e.ref)} — ${escapeHtml(e.detail)}`;
    list.appendChild(li);
  }
  details.appendChild(list);
  bubble.appendChild(details);
}

function showWelcome() {
  clearChat();
  const w = document.createElement("div");
  w.className = "welcome";
  w.innerHTML = `
    <h2>Start an investigation</h2>
    <p>I reason over the telemetry and back every conclusion with evidence —
       distinguishing Facts, Hypotheses, Recommendations, and Unknowns.</p>
    <div class="examples"></div>`;
  const examples = [
    "Is the system healthy right now?",
    "What changed recently?",
    "Why is checkout slow?",
    "Is this customer-impacting?",
  ];
  const box = w.querySelector(".examples");
  for (const ex of examples) {
    const c = document.createElement("button");
    c.className = "chip";
    c.textContent = ex;
    c.onclick = () => { input.value = ex; sendMessage(); };
    box.appendChild(c);
  }
  chat.appendChild(w);
}

// ---------- workspace panel ----------
function confChip(conf) {
  return conf ? `<span class="conf conf-${conf}">${conf}</span>` : "";
}

function renderWorkspace(ws) {
  wsBody.innerHTML = "";
  wsSnapshot.textContent = ws && ws.snapshot_seq ? `v${ws.snapshot_seq}` : "";
  if (!ws || !ws.has_investigation || !ws.sections || !ws.sections.length) {
    wsBody.innerHTML = `<div class="ws-empty">Ask a question to start building the investigation.</div>`;
    return;
  }
  for (const s of ws.sections) {
    if (s.kind === "empty") continue;
    const sec = document.createElement("div");
    sec.className = "ws-section";
    sec.innerHTML = `<h4>${escapeHtml(s.title)}</h4>`;
    sec.insertAdjacentHTML("beforeend", sectionBody(s));
    wsBody.appendChild(sec);
  }
}

function sectionBody(s) {
  switch (s.kind) {
    case "text":
      return `<p>${escapeHtml(s.text)}</p>`;
    case "claims":
      return "<ul>" + s.items.map((i) =>
        `<li>${escapeHtml(i.claim)}${confChip(i.confidence)}</li>`).join("") + "</ul>";
    case "list":
      return "<ul>" + s.items.map((i) => `<li>${escapeHtml(i)}</li>`).join("") + "</ul>";
    case "tags":
    case "empty":
      return `<div class="chip-row">` +
        (s.items || []).map((i) => `<span class="tag">${escapeHtml(i)}</span>`).join("") + `</div>`;
    case "timeline":
      return s.items.map((i) =>
        `<div class="tl-row"><span class="sev-dot sev-${i.severity}"></span>` +
        `<span class="tl-time">${escapeHtml(i.time)}</span>` +
        `<span class="tl-title">${escapeHtml(i.title)}</span></div>`).join("");
    case "evidence":
      return "<ul>" + s.items.map((i) =>
        `<li><span class="ev-kind">[${escapeHtml(i.kind)}]</span> ${escapeHtml(i.detail)}</li>`).join("") + "</ul>";
    case "hypotheses":
      return s.items.map((h) => {
        const missing = (h.missing && h.missing.length)
          ? `<div class="missing">Missing: ${escapeHtml(h.missing.join(", "))}</div>` : "";
        return `<div class="hyp"><div class="stmt">${escapeHtml(h.statement)}${confChip(h.confidence)}</div>${missing}</div>`;
      }).join("");
    case "kv":
      return s.items.map((i) =>
        `<div class="kv"><span class="k">${escapeHtml(i.label)}</span>${confChip(i.value)}</div>`).join("");
    default:
      return "";
  }
}

// ---------- conversation list ----------
function renderConvoList() {
  convoList.innerHTML = "";
  if (!state.conversations.length) {
    convoList.innerHTML = `<div class="empty">No investigations yet.</div>`;
    return;
  }
  for (const c of state.conversations) {
    const el = document.createElement("div");
    el.className = "convo" + (c.id === state.currentId ? " active" : "");
    el.innerHTML =
      `<div class="convo-name">${escapeHtml(c.title || "Untitled")}</div>` +
      `<div class="convo-meta">${c.message_count} msg · ${relativeTime(c.updated_at)}</div>`;
    el.onclick = () => openConversation(c.id);
    convoList.appendChild(el);
  }
}

// ---------- actions ----------
async function refreshStatus() {
  try {
    const { data: s } = await api("GET", "/api/status");
    const parts = [`source: ${s.data_source}`, s.anthropic_configured ? "Claude ✓" : "Claude ✗"];
    if (s.data_source === "datadog") parts.push(s.datadog_configured ? "Datadog ✓" : "Datadog ✗");
    banner.textContent = parts.join("  ·  ");
    banner.className = "status " + (s.anthropic_configured ? "ok" : "warn");
  } catch {
    banner.textContent = "status unavailable";
    banner.className = "status warn";
  }
}

async function loadConversations() {
  const { data } = await api("GET", "/api/conversations");
  state.configured = !!data.configured;
  state.conversations = data.conversations || [];
  renderConvoList();
  if (!state.configured) {
    setComposerEnabled(false);
    clearChat();
    addMessage("assistant",
      "Claude isn't configured yet. Add ANTHROPIC_API_KEY to a local .env file and restart " +
      "to enable evidence-backed investigations.");
    return;
  }
  setComposerEnabled(true);
  const last = localStorage.getItem(LAST_KEY);
  const pick = state.conversations.find((c) => c.id === last) || state.conversations[0];
  if (pick) openConversation(pick.id);
  else newConversation();
}

async function openConversation(cid) {
  const { ok, data } = await api("GET", `/api/conversations/${cid}`);
  if (!ok) return;
  state.currentId = cid;
  localStorage.setItem(LAST_KEY, cid);
  convoTitle.textContent = data.title || "Investigation";
  renderConvoList();
  clearChat();
  if (!data.messages || !data.messages.length) {
    showWelcome();
  } else {
    for (const m of data.messages) {
      if (m.role === "assistant") {
        const b = addMessage("assistant", m.content, { markdown: true });
      } else {
        addMessage("user", m.content);
      }
    }
  }
  renderWorkspace(data.workspace);
}

async function newConversation() {
  const { ok, data } = await api("POST", "/api/conversations", {});
  if (!ok) return;
  state.currentId = data.id;
  await loadConvoListOnly();
  openConversation(data.id);
}

async function loadConvoListOnly() {
  const { data } = await api("GET", "/api/conversations");
  state.conversations = data.conversations || [];
  renderConvoList();
}

function setComposerEnabled(on) {
  input.disabled = !on;
  sendBtn.disabled = !on;
  genSummaryBtn.disabled = !on;
}

async function sendMessage() {
  const message = input.value.trim();
  if (!message || !state.currentId) return;
  // Remove the welcome block on first message.
  if (chat.querySelector(".welcome")) clearChat();
  addMessage("user", message);
  input.value = "";
  autoGrow();
  setComposerEnabled(false);
  const thinking = addMessage("assistant", "Investigating…");
  try {
    const { ok, data } = await api("POST", `/api/conversations/${state.currentId}/chat`,
      { message, persona: personaSel.value });
    if (!ok) { thinking.textContent = data.error || "Something went wrong."; return; }
    thinking.querySelector("div").innerHTML = renderMarkdown(data.reply);
    attachEvidence(thinking, data.evidence);
    renderWorkspace(data.workspace);
    convoTitle.textContent = (await api("GET", `/api/conversations/${state.currentId}`)).data.title || convoTitle.textContent;
    loadConvoListOnly();
  } catch {
    thinking.textContent = "Something went wrong reaching the backend.";
  } finally {
    setComposerEnabled(true);
    input.focus();
  }
}

async function switchPersona() {
  if (!state.currentId) return;
  const { ok, data } = await api("POST", `/api/conversations/${state.currentId}/chat`,
    { message: "", persona: personaSel.value });
  if (!ok || data.no_investigation) { renderWorkspace(data.workspace); return; }
  const b = addMessage("assistant", data.reply, { markdown: true, tag: `Re-framed for ${data.persona_label}` });
  attachEvidence(b, data.evidence);
  renderWorkspace(data.workspace);
}

async function generateSummary() {
  if (!state.currentId) return;
  const bubble = addMessage("assistant", "Generating Incident Summary…", { artifact: true });
  const { ok, data } = await api("POST", `/api/conversations/${state.currentId}/artifact`,
    { key: "incident_summary" });
  if (!ok) { bubble.textContent = data.error || "Could not generate artifact."; return; }
  bubble.querySelector("div").innerHTML = renderMarkdown(data.markdown);
  chat.scrollTop = chat.scrollHeight;
}

// ---------- input behaviour ----------
function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

// ---------- events ----------
form.addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});
newChatBtn.addEventListener("click", newConversation);
personaSel.addEventListener("change", switchPersona);
genSummaryBtn.addEventListener("click", generateSummary);
toggleWsBtn.addEventListener("click", () => appEl.classList.toggle("ws-hidden"));

// ---------- init ----------
refreshStatus();
loadConversations();
