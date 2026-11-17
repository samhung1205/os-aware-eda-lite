/* Shared interface pieces for index.html and simulation.html: segmented controls, tables,
 * the key-measurement list, tooltip rows and small authored icons. Needs assets/charts.js. */
(function () {
  "use strict";
  const { esc } = window.Charts;

  // A strip of joined buttons, one pressed. Left / right arrow keys move between the options.
  function seg(name, options, current, onPick) {
    const wrap = document.createElement("div");
    wrap.className = "seg"; wrap.setAttribute("role", "group"); wrap.setAttribute("aria-label", name);
    options.forEach((o) => {
      const b = document.createElement("button");
      b.type = "button"; b.innerHTML = o.html || esc(o.label); b.setAttribute("aria-pressed", String(o.value === current));
      b.addEventListener("click", () => {
        wrap.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true"); onPick(o.value);
      });
      wrap.appendChild(b);
    });
    wrap.addEventListener("keydown", (e) => {
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!step || e.altKey || e.ctrlKey || e.metaKey) return;
      const buttons = [...wrap.querySelectorAll("button")];
      const i = buttons.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      buttons[(i + step + buttons.length) % buttons.length].focus();
    });
    return wrap;
  }
  function control(container, label, segEl) {
    const box = document.createElement("div");
    box.className = "control";
    box.innerHTML = `<span class="control-label">${esc(label)}</span>`;
    box.appendChild(segEl); container.appendChild(box);
    return box;
  }
  function table(headers, rows, opts) {
    opts = opts || {};
    const cls = (h) => `${h && h.l ? "l" : ""} ${h && h.wrap ? "wrap" : ""}`.trim();
    const th = headers.map((h) => `<th class="${cls(h)}">${h.html || esc(h.label)}</th>`).join("");
    const tr = rows.map((r) => `<tr class="${r.hl ? "hl" : ""}">${r.cells.map((c, i) => `<td class="${cls(headers[i])}">${c}</td>`).join("")}</tr>`).join("");
    const t = `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
    return opts.toggle ? `<details class="table-toggle"${opts.open ? " open" : ""}><summary>${esc(opts.toggle)}</summary>${t}</details>` : t;
  }
  // Key measurements: [{ label, value, unit, detail }] (label / unit / detail are trusted HTML).
  // kind "est" sets the values in the estimate voice (simulation page), never the measured ink.
  function spec(items, kind) {
    return `<dl class="spec${kind === "est" ? " est" : ""}">${items.filter(Boolean).map((it) => `<div class="spec-item"><dt>${it.label}</dt>` +
      `<dd class="v">${it.value}${it.unit ? `<span class="unit">${it.unit}</span>` : ""}</dd><dd class="d">${it.detail || ""}</dd></div>`).join("")}</dl>`;
  }
  const tipRows = (title, rows) => `<b>${esc(title)}</b>` + rows.map(([k, v]) => `<div class="row"><span>${esc(k)}</span><span>${v}</span></div>`).join("");
  const sw = (color) => `<span class="sw" style="background:${color}"></span>`;
  const ICON = {
    arrow: `<svg viewBox="0 0 14 10" aria-hidden="true"><path d="M0 5h12M8 1l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
    check: `<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M2 7.5l3.2 3.2L12 3.6" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
    cross: `<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
  };

  // Wide tables scroll sideways inside .table-wrap; mark the ones that do, so CSS can fade the hidden edge.
  function markScroll(w) {
    const more = w.scrollWidth > w.clientWidth + 1;
    if (w.classList.contains("scrolls") !== more) w.classList.toggle("scrolls", more);
    const end = !more || w.scrollLeft + w.clientWidth >= w.scrollWidth - 2;
    if (w.classList.contains("at-end") !== end) w.classList.toggle("at-end", end);
  }
  let queued = 0;
  const markAll = () => { cancelAnimationFrame(queued); queued = requestAnimationFrame(() => document.querySelectorAll(".table-wrap").forEach(markScroll)); };
  document.addEventListener("scroll", (e) => { if (e.target.classList && e.target.classList.contains("table-wrap")) markScroll(e.target); }, true);
  document.addEventListener("toggle", markAll, true); // a <details> holding a table opened
  window.addEventListener("resize", markAll);
  // views render after load; watch for tables being added (class changes are attributes, not child changes)
  new MutationObserver(markAll).observe(document.documentElement, { childList: true, subtree: true });

  window.UI = { seg, control, table, spec, tipRows, sw, ICON };
})();
