"use strict";
/* Tiny dependency-free canvas charts (bar / stacked-bar / line / doughnut).
   No external library — fully offline. Crisp on HiDPI via devicePixelRatio.
   A single shared tooltip div is reused across charts. */

const Charts = (() => {
  const PALETTE = ["#7c5cff", "#2ec16b", "#f5a623", "#ef5350", "#38bdf8",
                   "#e879f9", "#facc15", "#22d3ee"];
  const AXIS = "#6b7280", GRID = "#262b3a", TEXT = "#9aa3b2";
  const FONT = "11px -apple-system, Segoe UI, Roboto, sans-serif";

  let tip;
  function tooltip() {
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      tip.style.display = "none";
      document.body.appendChild(tip);
    }
    return tip;
  }
  function showTip(x, y, html) {
    const t = tooltip();
    t.innerHTML = html;
    t.style.display = "block";
    t.style.left = (x + 14) + "px";
    t.style.top = (y + 14) + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }

  function setup(canvas, height) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || canvas.parentElement.clientWidth || 360;
    const cssH = height || 220;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    canvas.style.height = cssH + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    return { ctx, W: cssW, H: cssH };
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const pow = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / pow;
    const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * pow;
  }
  function fmt(n) {
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return "" + (Math.round(n * 100) / 100);
  }

  function axes(ctx, W, H, pad, maxY, labels, every) {
    ctx.font = FONT; ctx.fillStyle = TEXT; ctx.strokeStyle = GRID; ctx.lineWidth = 1;
    const plotH = H - pad.t - pad.b, plotW = W - pad.l - pad.r;
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + plotH * (i / 4);
      const val = maxY * (1 - i / 4);
      ctx.strokeStyle = GRID;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      ctx.fillStyle = TEXT; ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(fmt(val), pad.l - 6, y);
    }
    ctx.fillStyle = TEXT; ctx.textAlign = "center"; ctx.textBaseline = "top";
    const stride = every || Math.ceil(labels.length / 12) || 1;
    labels.forEach((lab, i) => {
      if (i % stride !== 0) return;
      const x = pad.l + plotW * (labels.length === 1 ? 0.5 : i / (labels.length - 1 || 1));
      ctx.fillText("" + lab, x, H - pad.b + 6);
    });
    return { plotH, plotW };
  }

  function legend(container, series) {
    const el = document.createElement("div");
    el.className = "chart-legend";
    series.forEach(s => {
      const item = document.createElement("span");
      item.innerHTML = `<i style="background:${s.color}"></i>${s.name}`;
      el.appendChild(item);
    });
    container.appendChild(el);
  }

  // ---- bar / stacked bar ----
  function bar(canvas, { labels, series, stacked = false, height }) {
    const { ctx, W, H } = setup(canvas, height);
    const pad = { t: 12, r: 12, b: 26, l: 44 };
    let maxY = 0;
    if (stacked) {
      labels.forEach((_, i) => { maxY = Math.max(maxY, series.reduce((a, s) => a + (s.data[i] || 0), 0)); });
    } else {
      series.forEach(s => s.data.forEach(v => maxY = Math.max(maxY, v || 0)));
    }
    maxY = niceMax(maxY);
    const { plotH, plotW } = axes(ctx, W, H, pad, maxY, labels);
    const n = labels.length || 1;
    const slot = plotW / n;
    const groupW = slot * 0.7;
    const hit = [];
    labels.forEach((lab, i) => {
      const x0 = pad.l + slot * i + (slot - groupW) / 2;
      if (stacked) {
        let yAcc = 0;
        series.forEach(s => {
          const v = s.data[i] || 0; const h = (v / maxY) * plotH;
          const y = pad.t + plotH - yAcc - h;
          ctx.fillStyle = s.color; ctx.fillRect(x0, y, groupW, h);
          yAcc += h;
        });
        hit.push({ x: x0, w: groupW, i });
      } else {
        const bw = groupW / series.length;
        series.forEach((s, si) => {
          const v = s.data[i] || 0; const h = (v / maxY) * plotH;
          const x = x0 + bw * si;
          ctx.fillStyle = s.color; ctx.fillRect(x, pad.t + plotH - h, bw * 0.9, h);
        });
        hit.push({ x: x0, w: groupW, i });
      }
    });
    attachHover(canvas, hit, (i) => tipRows(labels[i], series, i));
  }

  // ---- line ----
  function line(canvas, { labels, series, height, fill = false }) {
    const { ctx, W, H } = setup(canvas, height);
    const pad = { t: 12, r: 12, b: 26, l: 44 };
    let maxY = 0; series.forEach(s => s.data.forEach(v => maxY = Math.max(maxY, v || 0)));
    maxY = niceMax(maxY);
    const { plotH, plotW } = axes(ctx, W, H, pad, maxY, labels);
    const n = labels.length;
    const X = i => pad.l + plotW * (n === 1 ? 0.5 : i / (n - 1 || 1));
    const Y = v => pad.t + plotH - (v / maxY) * plotH;
    series.forEach(s => {
      ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
      s.data.forEach((v, i) => { const x = X(i), y = Y(v || 0); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      if (fill) {
        ctx.lineTo(X(n - 1), pad.t + plotH); ctx.lineTo(X(0), pad.t + plotH); ctx.closePath();
        ctx.fillStyle = s.color + "22"; ctx.fill();
      }
      ctx.fillStyle = s.color;
      s.data.forEach((v, i) => { ctx.beginPath(); ctx.arc(X(i), Y(v || 0), 2.5, 0, 7); ctx.fill(); });
    });
    const hit = labels.map((_, i) => ({ x: X(i) - 6, w: 12, i }));
    attachHover(canvas, hit, (i) => tipRows(labels[i], series, i));
  }

  // ---- doughnut ----
  function doughnut(canvas, { labels, data, colors, height }) {
    const { ctx, W, H } = setup(canvas, height || 200);
    const cx = W / 2, cy = H / 2, r = Math.min(W, H) / 2 - 10, ir = r * 0.6;
    const total = data.reduce((a, b) => a + b, 0) || 1;
    let a0 = -Math.PI / 2;
    const arcs = [];
    data.forEach((v, i) => {
      const a1 = a0 + (v / total) * Math.PI * 2;
      ctx.beginPath(); ctx.moveTo(cx, cy);
      ctx.fillStyle = (colors && colors[i]) || PALETTE[i % PALETTE.length];
      ctx.arc(cx, cy, r, a0, a1); ctx.closePath(); ctx.fill();
      arcs.push({ a0, a1, i }); a0 = a1;
    });
    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath(); ctx.arc(cx, cy, ir, 0, 7); ctx.fill();
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = TEXT; ctx.font = "13px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(total + "", cx, cy);
    canvas.onmousemove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const dx = e.clientX - rect.left - cx, dy = e.clientY - rect.top - cy;
      const dist = Math.hypot(dx, dy);
      if (dist < ir || dist > r) { hideTip(); return; }
      let ang = Math.atan2(dy, dx); if (ang < -Math.PI / 2) ang += Math.PI * 2;
      const hitArc = arcs.find(a => ang >= a.a0 && ang < a.a1);
      if (hitArc) showTip(e.clientX, e.clientY,
        `<b>${labels[hitArc.i]}</b><br>${data[hitArc.i]} (${Math.round(data[hitArc.i] / total * 100)}%)`);
    };
    canvas.onmouseleave = hideTip;
  }

  function tipRows(label, series, i) {
    let html = `<b>${label}</b>`;
    series.forEach(s => { html += `<br><i style="background:${s.color}"></i>${s.name}: ${fmt(s.data[i] || 0)}`; });
    return html;
  }

  function attachHover(canvas, hit, htmlFor) {
    canvas.onmousemove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const h = hit.find(b => x >= b.x && x <= b.x + b.w) ||
                hit.reduce((best, b) => Math.abs((b.x + b.w / 2) - x) < Math.abs((best.x + best.w / 2) - x) ? b : best, hit[0]);
      if (h) showTip(e.clientX, e.clientY, htmlFor(h.i)); else hideTip();
    };
    canvas.onmouseleave = hideTip;
  }

  return { bar, line, doughnut, PALETTE };
})();
