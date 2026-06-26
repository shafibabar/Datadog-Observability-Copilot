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
    thinking.textContent = data.reply ?? "(no reply)";
  } catch {
    thinking.textContent = "Something went wrong reaching the backend.";
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

refreshStatus();
