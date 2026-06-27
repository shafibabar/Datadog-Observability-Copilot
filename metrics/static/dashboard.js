"use strict";
/* Fetches /api/metrics and renders the dashboard. Polls for a live view. */

const C = Charts.PALETTE;

function card(label, value, sub) {
  return `<div class="card"><div class="card-val">${value}</div>
    <div class="card-lab">${label}</div>${sub ? `<div class="card-sub">${sub}</div>` : ""}</div>`;
}

function carryForward(rows, key) {
  // Build a series that carries the last known value across prompts (for tests).
  let last = 0;
  return rows.map(r => { if (r[key] != null) last = r[key]; return last; });
}

function render(data) {
  const s = data.summary, rows = data.prompts;
  const labels = rows.map(r => r.index);

  document.getElementById("cards").innerHTML = [
    card("Prompts", s.total_prompts, `${s.intent_split.implementation} impl · ${s.intent_split.planning_qa} planning`),
    card("Output tokens", fmtN(s.total_output_tokens), `${fmtN(s.total_input_tokens)} input`),
    card("Peak tests passing", s.peak_tests_passing, `${s.total_tests_added} added total`),
    card("Lines added", fmtN(s.total_lines_added), `${fmtN(s.total_lines_removed)} removed`),
    card("Files created", s.total_files_created, `${s.total_files_modified} modified`),
    card("Est. cost (USD)", "$" + s.estimated_cost_usd.toFixed(2), "approx"),
  ].join("");

  Charts.bar(document.getElementById("c_tokens"), {
    labels, stacked: true, series: [
      { name: "input", color: C[0], data: rows.map(r => r.input) },
      { name: "output", color: C[1], data: rows.map(r => r.output) },
    ]
  });

  Charts.line(document.getElementById("c_cumtokens"), {
    labels, fill: true, series: [
      { name: "cumulative output", color: C[1], data: rows.map(r => r.cumulative_output) },
    ]
  });

  Charts.line(document.getElementById("c_tests"), {
    labels, fill: true, series: [
      { name: "tests passing", color: C[1], data: carryForward(rows, "tests_passing") },
    ]
  });

  Charts.bar(document.getElementById("c_testsadded"), {
    labels, series: [{ name: "tests added", color: C[4], data: rows.map(r => r.tests_added) }]
  });

  Charts.bar(document.getElementById("c_lines"), {
    labels, series: [
      { name: "added", color: C[1], data: rows.map(r => r.lines_added) },
      { name: "removed", color: C[3], data: rows.map(r => r.lines_removed) },
    ]
  });

  Charts.bar(document.getElementById("c_files"), {
    labels, stacked: true, series: [
      { name: "created", color: C[1], data: rows.map(r => r.files_created) },
      { name: "modified", color: C[2], data: rows.map(r => r.files_modified) },
      { name: "deleted", color: C[3], data: rows.map(r => r.files_deleted) },
    ]
  });

  Charts.bar(document.getElementById("c_duration"), {
    labels, series: [{ name: "seconds", color: C[5], data: rows.map(r => r.duration_sec) }]
  });

  Charts.doughnut(document.getElementById("c_intent"), {
    labels: ["planning / Q&A", "implementation"],
    data: [data.intent_split.planning_qa, data.intent_split.implementation],
    colors: [C[2], C[0]],
  });
  document.getElementById("lg_intent").innerHTML =
    `<div class="chart-legend"><span><i style="background:${C[2]}"></i>planning</span>` +
    `<span><i style="background:${C[0]}"></i>implementation</span></div>`;

  const docs = data.docs_context.per_file;
  const dnames = Object.keys(docs);
  Charts.bar(document.getElementById("c_docs"), {
    labels: dnames, series: [{ name: "updates", color: C[6], data: dnames.map(d => docs[d]) }]
  });

  Charts.line(document.getElementById("c_cost"), {
    labels, fill: true, series: [{
      name: "cumulative $", color: C[2],
      data: rows.reduce((acc, r) => { acc.push((acc.length ? acc[acc.length - 1] : 0) + r.cost_usd); return acc; }, [])
    }]
  });

  document.getElementById("updated").textContent = "updated " + new Date().toLocaleTimeString();
}

function fmtN(n) {
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return "" + n;
}

async function refresh() {
  try {
    const r = await fetch("/api/metrics");
    render(await r.json());
  } catch (e) {
    document.getElementById("updated").textContent = "fetch failed";
  }
}

let timer = null;
function setLive(on) {
  if (timer) { clearInterval(timer); timer = null; }
  if (on) timer = setInterval(refresh, 5000);
}
document.getElementById("auto").addEventListener("change", e => setLive(e.target.checked));
window.addEventListener("resize", () => refresh());

refresh();
setLive(true);
