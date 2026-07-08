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
const wsBody = $("ws-body");
const wsSnapshot = $("ws-snapshot");
const durationSel = $("duration-select");
const rangeModal = $("range-modal");
const rangeStart = $("range-start");
const rangeEnd = $("range-end");
const rangeApply = $("range-apply");
const rangeCancel = $("range-cancel");
const rangeError = $("range-error");
const scopeHint = $("scope-hint");
let prevDuration = "1h";   // last non-cancelled duration, to revert if custom is cancelled

// ---------- state ----------
const state = { configured: false, currentId: null, conversations: [], busy: false };
const scope = { environments: [], tenants: [] };
const LAST_KEY = "copilot.lastConversation";
const DAY_MS = 86400000;
const PRESET_MS = { "1h": 3600000, "2h": 7200000, "4h": 14400000, "8h": 28800000,
                    "1d": DAY_MS, "2d": 2 * DAY_MS, "1w": 7 * DAY_MS };

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

// Subsequence fuzzy match: every char of the query appears in order in the text.
function fuzzy(text, q) {
  let i = 0;
  for (const ch of q) { i = text.indexOf(ch, i); if (i < 0) return false; i++; }
  return true;
}

// ---------- multi-select with type-to-filter ----------
const SEARCH_THRESHOLD = 8;  // only show the filter box once a list gets long

function createMultiSelect(mount, { label, onChange }) {
  mount.innerHTML = "";
  const box = document.createElement("div");
  box.className = "ms";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ms-btn empty";
  const panel = document.createElement("div");
  panel.className = "ms-panel";
  panel.hidden = true;
  const search = document.createElement("input");
  search.className = "ms-search";
  search.placeholder = "Filter…";
  search.hidden = true;
  const list = document.createElement("div");
  list.className = "ms-list";
  panel.append(search, list);
  box.append(btn, panel);
  mount.append(box);

  let options = [];
  const selected = new Set();

  function renderBtn() {
    const n = selected.size;
    let text = label;
    if (n === 1) text = `${label}: ${[...selected][0]}`;
    else if (n > 1) text = `${label} · ${n}`;
    btn.textContent = text;
    const caret = document.createElement("span");
    caret.className = "ms-caret";
    caret.textContent = "⌄";
    btn.appendChild(caret);
    btn.classList.toggle("empty", n === 0);
    btn.classList.toggle("active", n > 0);
  }
  function renderList() {
    const q = search.value.trim().toLowerCase();
    list.innerHTML = "";
    const shown = options.filter((o) => !q || fuzzy(o.toLowerCase(), q));
    if (!shown.length) { list.innerHTML = `<div class="ms-empty">No matches</div>`; return; }
    for (const o of shown) {
      const row = document.createElement("label");
      row.className = "ms-opt";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selected.has(o);
      cb.onchange = () => {
        cb.checked ? selected.add(o) : selected.delete(o);
        renderBtn();
        onChange && onChange([...selected]);
      };
      const span = document.createElement("span");
      span.textContent = o;
      row.append(cb, span);
      list.append(row);
    }
  }
  btn.onclick = () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      search.value = "";
      search.hidden = options.length <= SEARCH_THRESHOLD;
      renderList();
      if (!search.hidden) search.focus();
    }
  };
  search.oninput = renderList;
  document.addEventListener("click", (e) => { if (!box.contains(e.target)) panel.hidden = true; });
  renderBtn();

  return {
    setOptions(next) {
      options = (next || []).slice();
      for (const s of [...selected]) if (!options.includes(s)) selected.delete(s);
      renderBtn();
      if (!panel.hidden) renderList();
    },
    setSelected(vals) {
      selected.clear();
      for (const v of vals || []) selected.add(v);
      renderBtn();
      if (!panel.hidden) renderList();
    },
    getSelected() { return [...selected]; },
  };
}

let envMS = null;
let tenantMS = null;

// ---------- scope ----------
function currentWindow() {
  const dur = durationSel.value;
  if (dur === "custom") {
    return {
      start: rangeStart.value ? new Date(rangeStart.value) : null,
      end: rangeEnd.value ? new Date(rangeEnd.value) : null,
    };
  }
  const end = new Date();
  return { start: new Date(end.getTime() - (PRESET_MS[dur] || PRESET_MS["1h"])), end };
}

function scopeValid() {
  if (scope.environments.length === 0 && scope.tenants.length === 0) return false;
  const { start, end } = currentWindow();
  if (!start || !end || isNaN(start) || isNaN(end)) return false;
  if (end <= start) return false;
  if (end - start > 7 * DAY_MS) return false;
  return true;
}

function scopeMessage() {
  if (scope.environments.length === 0 && scope.tenants.length === 0)
    return "Select at least one environment or tenant to investigate.";
  const { start, end } = currentWindow();
  if (!start || !end || isNaN(start) || isNaN(end)) return "Choose a start and end for the custom range.";
  if (end <= start) return "The end of the range must be after its start.";
  if (end - start > 7 * DAY_MS) return "A custom range can’t exceed 7 days.";
  return "";
}

function scopePayload() {
  const { start, end } = currentWindow();
  return {
    environments: scope.environments,
    tenants: scope.tenants,
    start: start.toISOString(),
    end: end.toISOString(),
  };
}

function refreshComposer() {
  const ready = state.configured && !!state.currentId && scopeValid() && !state.busy;
  sendBtn.disabled = !ready;
  input.disabled = !state.configured || state.busy;
  genSummaryBtn.disabled = !state.configured || !state.currentId || state.busy;
  scopeHint.textContent =
    (state.configured && state.currentId && !state.busy) ? scopeMessage() : "";
}

function toLocalInput(d) {
  // datetime-local wants "YYYY-MM-DDTHH:MM" in local time.
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function setRangeBounds() {
  // No future dates; nothing older than 2 years (computed from the system clock).
  const now = new Date();
  const twoYearsAgo = new Date(now);
  twoYearsAgo.setFullYear(now.getFullYear() - 2);
  rangeStart.min = toLocalInput(twoYearsAgo);
  rangeStart.max = toLocalInput(now);
  const s = rangeStart.value ? new Date(rangeStart.value) : null;
  rangeEnd.min = toLocalInput(s || twoYearsAgo);
  const cap = s ? new Date(Math.min(s.getTime() + 7 * DAY_MS, now.getTime())) : now;
  rangeEnd.max = toLocalInput(cap);
}

function shortDate(d) {
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function customRangeError(start, end) {
  const now = new Date();
  const twoYearsAgo = new Date(now);
  twoYearsAgo.setFullYear(now.getFullYear() - 2);
  if (!start || !end || isNaN(start) || isNaN(end)) return "Choose both a start and an end.";
  if (end <= start) return "The end must be after the start.";
  if (end - start > 7 * DAY_MS) return "The range can’t exceed 7 days.";
  if (end > now) return "The end can’t be in the future.";
  if (start < twoYearsAgo) return "The start can’t be more than 2 years ago.";
  return "";
}

function openRangeModal() {
  const now = new Date();
  if (!rangeEnd.value) rangeEnd.value = toLocalInput(now);
  if (!rangeStart.value) rangeStart.value = toLocalInput(new Date(now.getTime() - DAY_MS));
  setRangeBounds();
  rangeError.textContent = "";
  rangeModal.hidden = false;
}

function closeRangeModal() { rangeModal.hidden = true; }

function applyRange() {
  setRangeBounds();
  const { start, end } = currentWindow();
  const err = customRangeError(start, end);
  if (err) { rangeError.textContent = err; return; }
  const opt = durationSel.querySelector('option[value="custom"]');
  if (opt) opt.textContent = `${shortDate(start)} – ${shortDate(end)}`;
  prevDuration = "custom";
  closeRangeModal();
  refreshComposer();
}

function cancelRange() {
  // revert the dropdown to whatever was selected before opening the dialog
  durationSel.value = prevDuration;
  closeRangeModal();
  refreshComposer();
}

async function loadScopes(selectedEnvs) {
  const qs = selectedEnvs && selectedEnvs.length
    ? `?environments=${encodeURIComponent(selectedEnvs.join(","))}` : "";
  const { ok, data } = await api("GET", `/api/scopes${qs}`);
  if (!ok) return;
  if (!selectedEnvs) envMS.setOptions(data.environments || []);
  tenantMS.setOptions(data.tenants || []);
}

function setupControls() {
  envMS = createMultiSelect($("ctl-env"), {
    label: "Environment", placeholder: "Any environment",
    onChange: (vals) => {
      scope.environments = vals;
      loadScopes(vals).then(() => { scope.tenants = tenantMS.getSelected(); refreshComposer(); });
      refreshComposer();
    },
  });
  tenantMS = createMultiSelect($("ctl-tenant"), {
    label: "Tenant", placeholder: "Any tenant",
    onChange: (vals) => { scope.tenants = vals; refreshComposer(); },
  });

  durationSel.addEventListener("change", () => {
    if (durationSel.value === "custom") {
      openRangeModal();               // custom → pop up the From/To pickers
    } else {
      prevDuration = durationSel.value;
      const opt = durationSel.querySelector('option[value="custom"]');
      if (opt) opt.textContent = "Custom range…";   // reset any prior custom label
      refreshComposer();
    }
  });
  rangeStart.addEventListener("change", () => { setRangeBounds(); rangeError.textContent = ""; });
  rangeEnd.addEventListener("change", () => { rangeError.textContent = ""; });
  rangeApply.addEventListener("click", applyRange);
  rangeCancel.addEventListener("click", cancelRange);
  rangeModal.addEventListener("click", (e) => { if (e.target === rangeModal) cancelRange(); });
  personaSel.addEventListener("change", switchPersona);
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

// A copy-to-clipboard control that appears on every assistant reply.
function attachCopy(bubble, text) {
  const btn = document.createElement("button");
  btn.className = "copy-btn";
  btn.type = "button";
  btn.title = "Copy reply";
  btn.textContent = "Copy";
  btn.onclick = async () => {
    try {
      await navigator.clipboard.writeText(text || "");
      btn.textContent = "Copied ✓";
      setTimeout(() => { btn.textContent = "Copy"; }, 1200);
    } catch {
      btn.textContent = "Copy failed";
    }
  };
  bubble.appendChild(btn);
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
    <p>Pick an environment/tenant and a time window below, then ask. I reason over the
       telemetry and back every conclusion with evidence — distinguishing Facts,
       Hypotheses, Recommendations, and Unknowns.</p>
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
    c.onclick = () => { input.value = ex; autoGrow(); input.focus(); };  // fill, don't auto-send
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
    const main = document.createElement("div");
    main.className = "convo-main";
    main.innerHTML =
      `<div class="convo-name">${escapeHtml(c.title || "Untitled")}</div>` +
      `<div class="convo-meta">${c.message_count} msg · ${relativeTime(c.updated_at)}</div>`;
    main.onclick = () => openConversation(c.id);

    const menu = document.createElement("button");
    menu.className = "convo-menu";
    menu.type = "button";
    menu.title = "Rename or delete";
    menu.textContent = "⋯";
    menu.onclick = (e) => { e.stopPropagation(); openConvoMenu(menu, c); };

    el.append(main, menu);
    convoList.appendChild(el);
  }
}

function openConvoMenu(anchor, convo) {
  document.querySelectorAll(".convo-popup").forEach((p) => p.remove());
  const pop = document.createElement("div");
  pop.className = "convo-popup";
  const rename = document.createElement("button");
  rename.textContent = "Rename";
  rename.onclick = () => { pop.remove(); renameConversation(convo); };
  const del = document.createElement("button");
  del.className = "danger";
  del.textContent = "Delete";
  del.onclick = () => { pop.remove(); deleteConversation(convo.id); };
  pop.append(rename, del);
  const r = anchor.getBoundingClientRect();
  pop.style.top = `${r.bottom + 4}px`;
  pop.style.left = `${r.left - 80}px`;
  document.body.appendChild(pop);
  setTimeout(() => document.addEventListener("click", function h() {
    pop.remove(); document.removeEventListener("click", h);
  }), 0);
}

async function renameConversation(convo) {
  const title = window.prompt("Rename investigation", convo.title || "");
  if (title === null) return;
  const { ok } = await api("PATCH", `/api/conversations/${convo.id}`, { title });
  if (!ok) return;
  if (convo.id === state.currentId) convoTitle.textContent = title || convoTitle.textContent;
  loadConvoListOnly();
}

async function deleteConversation(cid) {
  if (!window.confirm("Delete this investigation? This can’t be undone.")) return;
  const { ok } = await api("DELETE", `/api/conversations/${cid}`);
  if (!ok) return;
  if (cid === state.currentId) { state.currentId = null; localStorage.removeItem(LAST_KEY); }
  await loadConvoListOnly();
  const next = state.conversations[0];
  if (next) openConversation(next.id); else newConversation();
}

// ---------- actions ----------
async function refreshStatus() {
  try {
    const { data: s } = await api("GET", "/api/status");
    const parts = [`source: ${s.data_source}`, s.anthropic_configured ? "Claude ✓" : "Claude ✗"];
    if (s.data_source === "datadog") parts.push(s.datadog_configured ? "Datadog ✓" : "Datadog ✗");
    banner.textContent = parts.join("  ·  ");
    banner.className = "status " + (s.anthropic_configured || s.data_source ? "ok" : "warn");
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
    refreshComposer();
    clearChat();
    addMessage("assistant",
      "Claude isn’t configured yet. Sign in to the Claude Code CLI (run `claude`) or add " +
      "ANTHROPIC_API_KEY to a local .env file, then restart to enable investigations.");
    return;
  }
  await loadScopes();
  const last = localStorage.getItem(LAST_KEY);
  const pick = state.conversations.find((c) => c.id === last) || state.conversations[0];
  if (pick) openConversation(pick.id);
  else newConversation();
}

async function applyScopeToControls(s) {
  // Reflect a conversation's persisted scope back into the controls when opened,
  // so the widgets show what the investigation is actually scoped to.
  scope.environments = (s && s.environments) || [];
  scope.tenants = (s && s.tenants) || [];
  envMS.setSelected(scope.environments);
  await loadScopes(scope.environments.length ? scope.environments : undefined);
  tenantMS.setSelected(scope.tenants);
}

async function openConversation(cid) {
  const { ok, data } = await api("GET", `/api/conversations/${cid}`);
  if (!ok) return;
  state.currentId = cid;
  localStorage.setItem(LAST_KEY, cid);
  convoTitle.textContent = data.title || "Investigation";
  await applyScopeToControls(data.scope);
  renderConvoList();
  clearChat();
  if (!data.messages || !data.messages.length) {
    showWelcome();
  } else {
    for (const m of data.messages) {
      if (m.role === "assistant") {
        const b = addMessage("assistant", m.content, { markdown: true });
        attachCopy(b, m.content);
      } else {
        addMessage("user", m.content);
      }
    }
  }
  renderWorkspace(data.workspace);
  refreshComposer();
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

async function sendMessage() {
  const message = input.value.trim();
  if (!message || !state.currentId || !scopeValid()) { refreshComposer(); return; }
  if (chat.querySelector(".welcome")) clearChat();
  addMessage("user", message);
  input.value = "";
  autoGrow();
  state.busy = true;
  refreshComposer();
  const thinking = addMessage("assistant", "Investigating…");
  try {
    const { ok, data } = await api("POST", `/api/conversations/${state.currentId}/chat`,
      { message, persona: personaSel.value, scope: scopePayload() });
    if (!ok) { thinking.textContent = data.error || "Something went wrong."; return; }
    thinking.querySelector("div").innerHTML = renderMarkdown(data.reply);
    if (!data.blocked) {
      attachEvidence(thinking, data.evidence);
      attachCopy(thinking, data.reply);
      convoTitle.textContent =
        (await api("GET", `/api/conversations/${state.currentId}`)).data.title || convoTitle.textContent;
      loadConvoListOnly();
    }
    renderWorkspace(data.workspace);
  } catch {
    thinking.textContent = "Something went wrong reaching the backend.";
  } finally {
    state.busy = false;
    refreshComposer();
    input.focus();
  }
}

async function switchPersona() {
  if (!state.currentId) return;
  const { ok, data } = await api("POST", `/api/conversations/${state.currentId}/chat`,
    { message: "", persona: personaSel.value });
  if (!ok || data.no_investigation) { if (data) renderWorkspace(data.workspace); return; }
  const b = addMessage("assistant", data.reply, { markdown: true, tag: `Re-framed for ${data.persona_label}` });
  attachCopy(b, data.reply);
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
  attachCopy(bubble, data.markdown);
  chat.scrollTop = chat.scrollHeight;
}

// ---------- input behaviour ----------
function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

// ---------- resizable / collapsible panels ----------
const widths = {
  sidebar: parseInt(localStorage.getItem("copilot.w.sidebar"), 10) || 268,
  ws: parseInt(localStorage.getItem("copilot.w.ws"), 10) || 360,
};

// Panel widths are CSS variables the flex layout reads; collapse is a class the
// CSS acts on. If this never runs, the CSS defaults already render correctly.
function applyLayout() {
  appEl.style.setProperty("--sidebar-w", widths.sidebar + "px");
  appEl.style.setProperty("--ws-w", widths.ws + "px");
}

function setupResizer(barId, side) {
  const bar = $(barId);
  let dragging = false;
  bar.addEventListener("pointerdown", (e) => {
    if (e.target.classList.contains("collapse")) return;  // chevron toggles, doesn't drag
    dragging = true;
    bar.setPointerCapture(e.pointerId);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  bar.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    let w = side === "left" ? e.clientX : window.innerWidth - e.clientX;
    w = Math.max(180, Math.min(560, w));
    widths[side === "left" ? "sidebar" : "ws"] = w;
    applyLayout();
  });
  const stop = () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    localStorage.setItem("copilot.w.sidebar", widths.sidebar);
    localStorage.setItem("copilot.w.ws", widths.ws);
  };
  bar.addEventListener("pointerup", stop);
  bar.addEventListener("pointercancel", stop);
}

function setupCollapse() {
  const restore = (key, cls) => { if (localStorage.getItem(key) === "1") appEl.classList.add(cls); };
  restore("copilot.collapsed.sidebar", "sidebar-collapsed");
  restore("copilot.collapsed.ws", "ws-collapsed");
  $("collapse-left").addEventListener("click", (e) => {
    e.stopPropagation();
    appEl.classList.toggle("sidebar-collapsed");
    localStorage.setItem("copilot.collapsed.sidebar", appEl.classList.contains("sidebar-collapsed") ? "1" : "0");
    applyLayout();
  });
  $("collapse-right").addEventListener("click", (e) => {
    e.stopPropagation();
    appEl.classList.toggle("ws-collapsed");
    localStorage.setItem("copilot.collapsed.ws", appEl.classList.contains("ws-collapsed") ? "1" : "0");
    applyLayout();
  });
}

// ---------- events ----------
form.addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});
newChatBtn.addEventListener("click", newConversation);
genSummaryBtn.addEventListener("click", generateSummary);

// ---------- init ----------
setupControls();
setupResizer("resize-left", "left");
setupResizer("resize-right", "right");
setupCollapse();
applyLayout();
refreshStatus();
loadConversations();
