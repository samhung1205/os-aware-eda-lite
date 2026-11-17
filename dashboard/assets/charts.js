/* Minimal SVG chart primitives for the dashboard. No dependencies.
 * Every mark that carries data has a data-tip (HTML) shown on hover / keyboard focus.
 * Notation (see assets/style.css): open bar = waiting, solid = measured service, red = past the
 * deadline, dashed line with a down arrow = the deadline. Line art is square-ended. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    if (attrs) for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function text(parent, x, y, str, attrs) {
    const t = svg("text", Object.assign({ x, y }, attrs || {}), parent);
    t.textContent = str;
    return t;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  function fmt(x, nd, signed) {
    if (x === null || x === undefined || !isFinite(x)) return "–";
    const s = Number(x).toFixed(nd === undefined ? 1 : nd);
    const v = signed && Number(s) > 0 ? "+" + s : s;
    return v.replace("-", "−");
  }
  function lin(d0, d1, r0, r1) {
    const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
    const f = (v) => r0 + (v - d0) * k;
    f.domain = [d0, d1];
    return f;
  }
  function niceStep(span, count) {
    const raw = span / Math.max(1, count);
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const m = raw / p;
    return (m >= 5 ? 10 : m >= 2 ? 5 : m >= 1 ? 2 : 1) * p;
  }
  function niceDomain(lo, hi, count, opts) {
    opts = opts || {};
    if (opts.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (lo === hi) { lo -= 1; hi += 1; }
    const step = niceStep(hi - lo, count || 5);
    const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step;
    const ticks = [];
    for (let v = a; v <= b + step / 2; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : +v.toFixed(10));
    return { lo: a, hi: b, ticks, step };
  }
  function tickFmt(v, step) {
    const nd = step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step)));
    return fmt(v, nd);
  }
  // Approximate text width: CJK and full-width characters are about 1 em, Latin about 0.56 em.
  function measure(str, size) {
    let n = 0;
    for (const ch of String(str)) n += /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]/.test(ch) ? 1 : 0.6;
    return n * (size || 12.5);
  }
  // A vertical reference (the deadline wherever it appears): dashed line, down arrow, label beside the arrow.
  function refMark(s, px, y0, y1, label, limit) {
    svg("line", { x1: px, x2: px, y1: y0, y2: y1, class: "refline" }, s);
    svg("path", { d: `M${px - 5},${y0 - 9}H${px + 5}L${px},${y0}Z`, class: "refhead" }, s);
    if (!label) return;
    const right = px + 9 + measure(label, 12) <= limit;
    text(s, right ? px + 9 : px - 9, y0 - 2, label, { class: "reflabel", "text-anchor": right ? "start" : "end" });
  }
  // 45° hatch fill used for time / frames past the deadline. Returns a url() for a fill attribute.
  function hatch(s, cls) {
    let defs = s.querySelector("defs");
    if (!defs) defs = s.insertBefore(document.createElementNS(NS, "defs"), s.firstChild);
    const id = `hatch${++uid}`;
    const p = svg("pattern", { id, patternUnits: "userSpaceOnUse", width: 5, height: 5, patternTransform: "rotate(45)" }, defs);
    svg("rect", { x: 0, y: 0, width: 2, height: 5, class: cls }, p);
    return `url(#${id})`;
  }
  const reduceMotion = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  let uid = 0;
  function width(container) { return Math.max(280, Math.floor(container.clientWidth || 640)); }

  const L = (window.I18N && window.I18N.L) || ((en) => en);
  // Plain-text version of a tooltip ("title: key value; key value") so the accessible name carries the
  // numbers, not just "Latest-Frame block 1".
  const scratch = document.createElement("div");
  function tipText(html) {
    scratch.innerHTML = html;
    const title = scratch.querySelector("b");
    const rows = [...scratch.querySelectorAll(".row")].map((r) => [...r.children].map((c) => c.textContent.trim()).join(" "));
    if (!rows.length) return scratch.textContent.replace(/\s+/g, " ").trim();
    return (title ? title.textContent.trim() + ": " : "") + rows.join("; ");
  }
  function tipAttrs(node, html, label) {
    if (!html) return;
    node.setAttribute("data-tip", html);
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "img");
    const t = tipText(html);
    const norm = (x) => x.replace(/[\s·:,;]+/g, " ").trim().toLowerCase();
    node.setAttribute("aria-label", label && !norm(t).includes(norm(label)) ? `${label}: ${t}` : t || label || "");
  }

  /* ---------- keyboard: one tab stop per chart, arrow keys move between its marks ---------- */
  function rove(container) {
    const s = container.querySelector("svg");
    const marks = [...container.querySelectorAll("[data-tip][tabindex]")];
    // A chart can name its entry point (the hero starts on the traced lane); otherwise the first mark.
    const entry = Math.max(0, marks.findIndex((m) => m.hasAttribute("data-entry")));
    marks.forEach((m, i) => m.setAttribute("tabindex", i === entry ? "0" : "-1"));
    // Ticks, labels and gridlines repeat what each mark's label already says; hide them from screen
    // readers so the chart reads as its labelled marks only.
    if (s) for (const el of s.children) if (!el.matches("[data-tip], defs") && !el.querySelector("[data-tip]")) el.setAttribute("aria-hidden", "true");
    if (s && marks.length > 1) {
      const base = (s.getAttribute("aria-label") || "").replace(/[.。\s]+$/, "");
      const lanes = marks.filter((m) => m.dataset.col === "0").length;
      const hint = lanes ? L(`${lanes} lanes and their blocks; up and down move between lanes, left and right through a lane's blocks`, `${lanes} 條 lane 與各自的 blocks；上下鍵切換 lane，左右鍵瀏覽該 lane 的 blocks`)
        : L(`${marks.length} data points; arrow keys move between them`, `${marks.length} 個資料點，可用方向鍵移動`);
      s.setAttribute("aria-label", base ? base + L(". ", "。") + hint : hint);
    }
  }
  const STEP = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  document.addEventListener("keydown", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip][tabindex]");
    const s = t && t.closest("svg");
    if (!s || e.altKey || e.ctrlKey || e.metaKey) return;
    const marks = [...s.querySelectorAll("[data-tip][tabindex]")];
    const i = marks.indexOf(t);
    let j;
    if (t.hasAttribute("data-row") && e.key in STEP) {
      // Up / Down move between rows (to the row's lane), Left / Right along the row (lane → its block dots).
      const row = +t.dataset.row, col = +t.dataset.col, vertical = e.key === "ArrowUp" || e.key === "ArrowDown";
      const at = (r, c) => marks.findIndex((m) => +m.dataset.row === r && +m.dataset.col === c);
      j = vertical ? at(row + STEP[e.key], 0) : at(row, col + STEP[e.key]);
      if (j < 0) j = i;
    } else if (e.key in STEP) j = Math.max(0, Math.min(marks.length - 1, i + STEP[e.key]));
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = marks.length - 1;
    else return;
    e.preventDefault();
    if (j === i) return;
    marks[i].setAttribute("tabindex", "-1");
    marks[j].setAttribute("tabindex", "0");
    marks[j].focus();
  });

  /* ---------- tooltip ---------- */
  let tipEl = null;
  let focusTip = null; // the [data-tip] mark that currently has keyboard focus
  function ensureTip() {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "tooltip";
      // Visual only: each mark's aria-label already carries the same text, so screen readers
      // would otherwise hear it twice on every focus.
      tipEl.setAttribute("aria-hidden", "true");
      document.body.appendChild(tipEl);
    }
    return tipEl;
  }
  function place(x, y) {
    const t = ensureTip();
    const r = t.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
    t.style.left = Math.max(8, left) + "px";
    t.style.top = Math.max(8, top) + "px";
  }
  function show(target, x, y) {
    const t = ensureTip();
    t.innerHTML = target.getAttribute("data-tip");
    t.classList.add("on");
    place(x, y);
  }
  function hide() { if (tipEl) tipEl.classList.remove("on"); }
  document.addEventListener("pointerover", (e) => {
    let t = e.target.closest && e.target.closest("[data-tip]");
    if (t && t.getAttribute("data-tip-hover") === "off") t = null;
    if (t) show(t, e.clientX, e.clientY);
    // A focused mark keeps its tooltip when the (possibly resting) pointer lands on something else,
    // e.g. after keyboard focus scrolls the page under a stationary mouse.
    else if (focusTip && focusTip.isConnected) show(focusTip, ...anchorOf(focusTip));
    else hide();
  });
  document.addEventListener("pointermove", (e) => {
    if (tipEl && tipEl.classList.contains("on")) place(e.clientX, e.clientY);
  });
  // Keyboard focus scrolls the mark into view; keep its tooltip attached instead of hiding it.
  const anchorOf = (t) => {
    const r = t.getBoundingClientRect(), fx = t.getAttribute("data-tip-x");
    return fx === null ? [r.right, r.top] : [r.left + r.width * +fx, r.bottom - 8];
  };
  document.addEventListener("focusin", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    focusTip = t || null;
    if (t) show(t, ...anchorOf(t)); else hide();
  });
  document.addEventListener("focusout", () => { focusTip = null; hide(); });
  window.addEventListener("scroll", () => {
    if (focusTip && focusTip.isConnected) place(...anchorOf(focusTip)); else hide();
  }, { passive: true });

  /* ---------- responsive mounting ---------- */
  const mounted = new Set();
  function mount(container, render) {
    const entry = { container, render, w: 0 };
    entry.run = () => {
      const w = width(container);
      if (w === entry.w && container.firstChild) return;
      entry.w = w;
      container.innerHTML = "";
      render(container, w);
      rove(container);
    };
    for (const e of mounted) if (e.container === container) mounted.delete(e);
    mounted.add(entry);
    entry.run();
    return entry;
  }
  let raf = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      for (const e of mounted) {
        if (!e.container.isConnected) { mounted.delete(e); continue; }
        if (e.container.offsetParent !== null) e.run();
      }
    });
  });
  function refreshVisible() {
    for (const e of mounted) if (e.container.isConnected && e.container.offsetParent !== null) { e.w = 0; e.run(); }
  }

  function groupLabel(s, y, str) {
    svg("rect", { x: 0, y: y - 13, width: measure(str, 12) * 0.96 + 4, height: 18, fill: "var(--surface)" }, s);
    text(s, 0, y, str, { class: "grouplabel" });
  }
  function xAxis(g, x, dom, y0, y1, opts) {
    opts = opts || {};
    for (const v of dom.ticks) {
      const px = Math.round(x(v)) + 0.5;
      svg("line", { x1: px, x2: px, y1: y0, y2: y1, class: v === 0 && opts.zeroStrong ? "zero" : "gridline" }, g);
      const tg = svg("g", { class: "tick" }, g);
      text(tg, px, y1 + 15, tickFmt(v, dom.step) + (opts.unit || ""), { "text-anchor": "middle" });
    }
    if (opts.title) {
      const tx = Math.max(x(dom.hi), Math.min(opts.width || x(dom.hi), measure(opts.title, 11.5)));
      text(g, tx, y1 + 32, opts.title, { class: "axis-title", "text-anchor": "end" });
    }
  }

  /* ---------- dotRows: one row per category, run dots + mean + min–max ---------- */
  function dotRows(container, cfg) {
    return mount(container, (el, W) => {
      const narrow = W < 560;
      const rows = cfg.rows;
      const labelW = Math.min(narrow ? 108 : 170, Math.max(...rows.map((r) => measure(r.label, 12.5))) + 14);
      const valueW = cfg.valueW !== undefined ? cfg.valueW : narrow ? 64 : 104;
      const rowH = cfg.rowH || 34, top = (cfg.refs || []).length || (cfg.band && cfg.band.label) ? 24 : 8, groupH = 26;
      let h = top;
      const layout = [];
      let lastGroup = null;
      for (const r of rows) {
        if (r.group && r.group !== lastGroup) { layout.push({ group: r.group, y: h }); h += groupH; lastGroup = r.group; }
        layout.push({ row: r, y: h + rowH / 2 }); h += rowH;
      }
      const plotBottom = h + 4, H = plotBottom + (cfg.xTitle ? 40 : 26);
      const vals = [];
      rows.forEach((r) => { vals.push(r.mean, r.min, r.max); (r.points || []).forEach((p) => vals.push(p.v)); });
      (cfg.refs || []).forEach((r) => vals.push(r.value));
      const finite = vals.filter((v) => v !== null && v !== undefined && isFinite(v));
      const dom = niceDomain(cfg.min !== undefined ? cfg.min : Math.min(...finite), cfg.max !== undefined ? cfg.max : Math.max(...finite), narrow ? 4 : 6, { zero: cfg.zero !== false });
      const x0 = labelW, x1 = W - valueW - 8;
      const x = lin(dom.lo, dom.hi, x0, x1);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel || "" }, el);
      if (cfg.band) {
        // highlighted x-range (e.g. "the zoomed chart above covers this range"); drawn under the axis
        const b0 = x(Math.max(dom.lo, cfg.band.lo)), b1 = x(Math.min(dom.hi, cfg.band.hi));
        svg("rect", { x: b0, y: top - 4, width: Math.max(2, b1 - b0), height: plotBottom - top + 4, class: "band" }, s);
        if (cfg.band.label) {
          const right = b0 + measure(cfg.band.label, 11) <= W;
          text(s, right ? b0 : b1, top - 10, cfg.band.label, { class: "bandlabel", "text-anchor": right ? "start" : "end" });
        }
      }
      xAxis(s, x, dom, top - 4, plotBottom, { title: cfg.xTitle, zeroStrong: true, width: W });
      for (const ref of cfg.refs || []) {
        refMark(s, x(ref.value), top - 6, plotBottom, ref.label, W);
      }
      for (const item of layout) {
        if (item.group) { groupLabel(s, item.y + 17, item.group); continue; }
        const r = item.row, y = item.y;
        text(s, 0, y + 4, r.label, { class: "rowlabel" + (r.dim ? " dim" : "") + (r.strong ? " strong" : "") });
        if (r.min !== null && r.max !== null && r.min !== undefined) {
          svg("line", { x1: x(r.min), x2: x(r.max), y1: y, y2: y, stroke: r.color, "stroke-width": 2, "stroke-linecap": "round", opacity: 0.45 }, s);
        }
        for (const p of r.points || []) {
          const c = svg("circle", { cx: x(p.v), cy: y, r: 4, fill: r.color, "fill-opacity": 0.55, class: "ring" }, s);
          tipAttrs(c, p.tip, p.label);
        }
        if (r.mean !== null && r.mean !== undefined) {
          if ((r.points || []).length) svg("line", { x1: x(r.mean), x2: x(r.mean), y1: y - 9, y2: y + 9, stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "butt" }, s);
          else svg("circle", { cx: x(r.mean), cy: y, r: 5, fill: r.color, class: "ring" }, s);
        }
        const hit = svg("rect", { x: 0, y: y - rowH / 2, width: W, height: rowH, class: "hit" }, s);
        s.insertBefore(hit, s.firstChild);
        tipAttrs(hit, r.tip, r.label);
        hit.removeAttribute("tabindex");
        text(s, W, y + 4, r.valueText !== undefined ? r.valueText : fmt(r.mean, cfg.nd), { "text-anchor": "end", class: "vlabel" + (r.dim ? " dim" : "") });
      }
    });
  }

  /* ---------- forest: paired differences with 95% CI ---------- */
  function forest(container, cfg) {
    return mount(container, (el, W) => {
      const narrow = W < 600;
      const rows = cfg.rows;
      const stacked = W < 520;
      const labelW = stacked ? 0 : narrow ? Math.min(W * 0.46, 200) : 260;
      const rowH = stacked ? 64 : 46, top = 10, groupH = 28;
      let h = top;
      const layout = [];
      let lastGroup = null;
      for (const r of rows) {
        if (r.group && r.group !== lastGroup) { layout.push({ group: r.group, y: h }); h += groupH; lastGroup = r.group; }
        layout.push({ row: r, y: h + rowH / 2 }); h += rowH;
      }
      const plotBottom = h, H = plotBottom + 40;
      const vals = [0];
      rows.forEach((r) => { vals.push(r.lo, r.hi, r.mean); (r.points || []).forEach((p) => vals.push(p.v)); });
      const finite = vals.filter((v) => v !== null && v !== undefined && isFinite(v));
      const dom = niceDomain(Math.min(...finite), Math.max(...finite), narrow ? 4 : 6, { zero: true });
      const x = lin(dom.lo, dom.hi, labelW + 10, W - 10);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel || "" }, el);
      xAxis(s, x, dom, top - 4, plotBottom, { title: cfg.xTitle, zeroStrong: true, width: W });
      for (const item of layout) {
        if (item.group) { groupLabel(s, item.y + 18, item.group); continue; }
        const r = item.row, y = item.y;
        if (stacked) {
          svg("rect", { x: 0, y: y - 33, width: Math.max(measure(r.label, 12.5), measure(r.sub || "", 11.5)) + 6, height: 32, fill: "var(--surface)" }, s);
          text(s, 0, y - 20, r.label, { class: "rowlabel" + (r.dim ? " dim" : "") });
          text(s, 0, y - 5, r.sub || "", { class: "vlabel dim", style: "font-size:11.5px" });
        } else {
          text(s, 0, y - 3, r.label, { class: "rowlabel" + (r.dim ? " dim" : "") });
          text(s, 0, y + 13, r.sub || "", { class: "vlabel dim", style: "font-size:11.5px" });
        }
        const yc = stacked ? y + 14 : y;
        if (r.lo !== null && r.hi !== null && isFinite(r.lo) && isFinite(r.hi)) {
          svg("line", { x1: x(r.lo), x2: x(r.hi), y1: yc, y2: yc, stroke: r.dim ? "var(--muted)" : "var(--ink)", "stroke-width": 2, "stroke-linecap": "butt" }, s);
          for (const v of [r.lo, r.hi]) svg("line", { x1: x(v), x2: x(v), y1: yc - 5, y2: yc + 5, stroke: r.dim ? "var(--muted)" : "var(--ink)", "stroke-width": 1.5 }, s);
        }
        // individual block differences: small open circles on the interval line
        for (const p of r.points || []) {
          const c = svg("circle", { cx: x(p.v), cy: yc, r: 3.4, stroke: r.color || "var(--ink)", class: "blockdot" }, s);
          tipAttrs(c, p.tip, p.label);
        }
        if (r.mean !== null && isFinite(r.mean)) {
          svg("circle", { cx: x(r.mean), cy: yc, r: 5.5, fill: r.color || "var(--ink)", class: "ring" }, s);
        }
        const hit = svg("rect", { x: 0, y: y - rowH / 2, width: W, height: rowH, class: "hit" }, s);
        s.insertBefore(hit, s.firstChild);
        tipAttrs(hit, r.tip, r.label);
      }
    });
  }

  /* ---------- line / scatter chart ---------- */
  function lineChart(container, cfg) {
    return mount(container, (el, W) => {
      const narrow = W < 560;
      const H = cfg.height || (narrow ? 260 : 300);
      const endW = cfg.endLabels ? Math.max(0, ...(cfg.series || []).map((sr) => measure(sr.name || "", 12))) + 14 : 0;
      const padL = cfg.yTitle ? 58 : 46, padR = cfg.endLabels ? Math.min(narrow ? 130 : 160, Math.max(narrow ? 40 : 60, endW)) : 16, padT = 14, padB = cfg.xTitle ? 46 : 30;
      const xs = [], ys = [];
      cfg.series.forEach((sr) => sr.points.forEach((p) => { xs.push(p.x); ys.push(p.y); }));
      (cfg.refs || []).forEach((r) => { if (r.y !== undefined) ys.push(r.y); if (r.x !== undefined) xs.push(r.x); });
      const xd = niceDomain(cfg.xMin !== undefined ? cfg.xMin : Math.min(...xs), cfg.xMax !== undefined ? cfg.xMax : Math.max(...xs), narrow ? 4 : 7, { zero: cfg.xZero !== false });
      const yd = niceDomain(cfg.yMin !== undefined ? cfg.yMin : Math.min(...ys), cfg.yMax !== undefined ? cfg.yMax : Math.max(...ys), 5, { zero: cfg.yZero !== false });
      const x = cfg.xTicks ? lin(cfg.xMin, cfg.xMax, padL, W - padR) : lin(xd.lo, xd.hi, padL, W - padR);
      const y = lin(yd.lo, yd.hi, H - padB, padT);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel || "" }, el);
      for (const v of yd.ticks) {
        const py = Math.round(y(v)) + 0.5;
        svg("line", { x1: padL, x2: W - padR, y1: py, y2: py, class: v === yd.lo ? "baseline" : "gridline" }, s);
        const tg = svg("g", { class: "tick" }, s);
        text(tg, padL - 8, py + 4, tickFmt(v, yd.step), { "text-anchor": "end" });
      }
      for (const v of cfg.xTicks || xd.ticks) {
        const tg = svg("g", { class: "tick" }, s);
        text(tg, x(v), H - padB + 17, cfg.xTickFmt ? cfg.xTickFmt(v) : tickFmt(v, xd.step), { "text-anchor": "middle" });
      }
      if (cfg.xTitle) text(s, W - padR, H - 8, cfg.xTitle, { class: "axis-title", "text-anchor": "end" });
      if (cfg.diag) {
        const lo = Math.max(xd.lo, yd.lo), hi = Math.min(xd.hi, yd.hi);
        svg("line", { x1: x(lo), y1: y(lo), x2: x(hi), y2: y(hi), class: "refline" }, s);
        let f = cfg.diagAt || 0.62;
        while (f > 0.2 && x(lo + (hi - lo) * f) + 8 + measure(cfg.diag, 11.5) > W - 4) f -= 0.04;
        const m = lo + (hi - lo) * f;
        text(s, x(m) + 8, y(m) + 16, cfg.diag, { class: "reflabel", "text-anchor": "start" });
      }
      const refLabels = [];
      for (const r of cfg.refs || []) {
        if (r.y !== undefined) {
          svg("line", { x1: padL, x2: W - padR, y1: y(r.y), y2: y(r.y), class: "refline" }, s);
          refLabels.push(r); // placed after the end labels are known (below)
        } else {
          refMark(s, x(r.x), padT + 8, H - padB, r.label, W - padR);
        }
      }
      const ends = [];
      for (const sr of cfg.series) {
        const pts = sr.points.slice().sort((a, b) => a.x - b.x);
        if (!cfg.scatter && pts.length > 1) {
          svg("path", { d: pts.map((p, i) => (i ? "L" : "M") + x(p.x).toFixed(1) + "," + y(p.y).toFixed(1)).join(""), fill: "none", stroke: sr.color, "stroke-width": 2, "stroke-dasharray": sr.dash, "stroke-linejoin": "round", "stroke-linecap": sr.dash ? "butt" : "round" }, s);
        }
        for (const p of pts) {
          const c = svg("circle", { cx: x(p.x), cy: y(p.y), r: cfg.scatter ? 4.5 : 4, fill: sr.color, class: "ring", "fill-opacity": cfg.scatter ? 0.8 : 1 }, s);
          tipAttrs(c, p.tip, sr.name);
        }
        if (cfg.endLabels && pts.length && sr.name) {
          const last = pts[pts.length - 1];
          ends.push({ x: x(last.x) + 8, y: y(last.y) + 4, name: sr.name });
        }
      }
      // end labels: keep at least 16 px apart vertically
      ends.sort((a, b) => a.y - b.y);
      for (let i = 1; i < ends.length; i++) {
        if (Math.abs(ends[i].x - ends[i - 1].x) < 60 && ends[i].y - ends[i - 1].y < 16) ends[i].y = ends[i - 1].y + 16;
      }
      // an end label that would sit on a horizontal reference line moves just above it
      for (const e of ends) for (const r of refLabels) if (Math.abs(e.y - 4 - y(r.y)) < 7) e.y = y(r.y) - 5;
      ends.forEach((e) => text(s, e.x, e.y, e.name, { class: "vlabel" }));
      // Reference labels sit right-aligned above their line, clear of curves rising through the left of
      // the plot; one that would meet an end label inside the plot goes under the line instead.
      for (const r of refLabels) {
        if (!r.label) continue;
        const x1 = W - padR - 4, x0 = x1 - measure(r.label, 12), ly = y(r.y);
        const hit = ends.some((e) => e.x < x1 && e.x + measure(e.name, 12.5) > x0 && Math.abs(e.y - 4 - (ly - 10)) < 14);
        text(s, x1, hit ? ly + 15 : ly - 6, r.label, { class: "reflabel", "text-anchor": "end" });
      }
      if (cfg.yTitle) {
        const t = text(s, 0, 0, cfg.yTitle, { class: "axis-title", transform: `translate(11 ${(H - padB + padT) / 2}) rotate(-90)`, "text-anchor": "middle" });
        t.setAttribute("x", 0);
      }
    });
  }

  /* ---------- horizontal (stacked) bars ---------- */
  function barPath(x0, x1, y, h) { return `M${x0},${y}H${x1}V${y + h}H${x0}Z`; }
  function hbars(container, cfg) {
    return mount(container, (el, W) => {
      const narrow = W < 560;
      const rows = cfg.rows;
      const labelW = Math.min(narrow ? 140 : 180, Math.max(...rows.map((r) => measure(r.label, 12.5))) + 14);
      const valueW = narrow ? 58 : 84;
      const rowH = cfg.rowH || 32, barH = Math.min(18, rowH - 12), top = (cfg.refs || []).length ? 24 : 8, groupH = 26;
      let h = top; const layout = []; let lastGroup = null;
      for (const r of rows) {
        if (r.group && r.group !== lastGroup) { layout.push({ group: r.group, y: h }); h += groupH; lastGroup = r.group; }
        layout.push({ row: r, y: h + rowH / 2 }); h += rowH;
      }
      const plotBottom = h, H = plotBottom + (cfg.xTitle ? 40 : 26);
      const totals = rows.map((r) => r.segments.reduce((a, sg) => a + Math.max(0, sg.v || 0), 0));
      const refs = (cfg.refs || []).map((r) => r.value);
      const dom = niceDomain(0, cfg.max !== undefined ? cfg.max : Math.max(...totals, ...refs), narrow ? 4 : 6, { zero: true });
      const x = lin(0, dom.hi, labelW, W - valueW);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel || "" }, el);
      let lateFill = null;
      xAxis(s, x, dom, top - 4, plotBottom, { title: cfg.xTitle, width: W });
      for (const ref of cfg.refs || []) {
        refMark(s, x(ref.value), top - 6, plotBottom, ref.label, W);
      }
      for (const item of layout) {
        if (item.group) { groupLabel(s, item.y + 17, item.group); continue; }
        const r = item.row, y = item.y;
        text(s, 0, y + 4, r.label, { class: "rowlabel" + (r.dim ? " dim" : "") });
        // optional release arrow at t = 0, the same mark as the overview lanes
        if (cfg.release) {
          const x0 = x(0), tip = y - barH / 2 - 7;
          svg("line", { x1: x0, x2: x0, y1: y + barH / 2, y2: tip + 6, class: "release" }, s);
          svg("path", { d: `M${x0 - 4},${tip + 6}H${x0 + 4}L${x0},${tip}Z`, class: "release", "stroke-width": 0 }, s);
        }
        let acc = 0;
        // A deadline reference with split: true cuts every solid segment at the deadline; the part past
        // it is drawn as the red late hatch, the same notation as the overview lanes.
        const cut = (cfg.refs || []).find((rf) => rf.split);
        const segs = [];
        r.segments.filter((sg) => (sg.v || 0) > 0).forEach((sg) => {
          if (cut && !sg.open && !sg.late && !sg.dropped && acc < cut.value && acc + sg.v > cut.value) {
            segs.push(Object.assign({}, sg, { v: cut.value - acc }), Object.assign({}, sg, { v: acc + sg.v - cut.value, late: true }));
          } else segs.push(sg);
          acc += sg.v;
        });
        acc = 0;
        segs.forEach((sg, i) => {
          const a = x(acc), b = x(acc + sg.v);
          const gap = i < segs.length - 1 && !sg.open && !sg.dropped && !segs[i + 1].late ? 2 : 0;
          if (b - a - gap > 0.5) {
            const box = { x: a + 0.75, y: y - barH / 2 + 0.75, width: Math.max(0, b - gap - a - 1.5), height: barH - 1.5 };
            const p = sg.open ? svg("rect", Object.assign(box, { class: "wait" }), s)
              : sg.dropped ? svg("rect", Object.assign(box, { class: "dropped" }), s)   // dashed outline: never processed
                : sg.late ? svg("rect", Object.assign(box, { class: "overshoot", fill: lateFill || (lateFill = hatch(s, "hatch-late")) }), s)
                  : svg("path", { d: barPath(a, b - gap, y - barH / 2, barH), fill: sg.color }, s);
            tipAttrs(p, sg.tip || r.tip, r.label + " " + (sg.name || ""));
          }
          acc += sg.v;
        });
        if (cut && acc > cut.value && !r.segments.some((sg) => sg.late)) r.lateValue = true;
        const endX = Math.max(x(acc), r.marker !== undefined && r.marker !== null ? x(r.marker) : 0);
        let vt = r.valueText !== undefined ? r.valueText : fmt(acc, cfg.nd);
        // A note that does not fit after the value moves under the bar; it is never dropped, because it
        // can be what keeps the bar from being misread.
        let below = false;
        if (r.valueNote) { if (endX + 7 + measure(vt + " · " + r.valueNote, 12) <= W) vt += " · " + r.valueNote; else below = true; }
        let lx = endX + 7;
        for (const ref of cfg.refs || []) { const px = x(ref.value); if (px > lx - 4 && px < lx + measure(vt, 12.5) + 4) lx = px + 7; }
        text(s, lx, y + 4, vt, { class: "vlabel" + (r.dim ? " dim" : "") + (r.lateValue ? " strong late" : "") });
        if (below) text(s, labelW, y + barH / 2 + 12, r.valueNote, { class: "vlabel dim small" });
        if (r.marker !== undefined && r.marker !== null) {
          svg("line", { x1: x(r.marker), x2: x(r.marker), y1: y - barH / 2 - 4, y2: y + barH / 2 + 4, stroke: "var(--ink)", "stroke-width": 2 }, s);
        }
      }
    });
  }

  /* ---------- slope: one line per block across ordered categories ---------- */
  function slope(container, cfg) {
    return mount(container, (el, W) => {
      const narrow = W < 520;
      const H = cfg.height || 280;
      const padL = cfg.yTitle ? 58 : 46, padR = narrow ? 18 : 40, padT = 16, padB = 34;
      const vals = [];
      cfg.lines.forEach((l) => l.values.forEach((v) => v !== null && vals.push(v)));
      const yd = niceDomain(Math.min(...vals), Math.max(...vals), 5, { zero: cfg.zero !== false });
      const n = cfg.categories.length;
      const x = (i) => padL + 24 + (i * (W - padL - padR - 48)) / Math.max(1, n - 1);
      const y = lin(yd.lo, yd.hi, H - padB, padT);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel || "" }, el);
      for (const v of yd.ticks) {
        const py = Math.round(y(v)) + 0.5;
        svg("line", { x1: padL, x2: W - padR, y1: py, y2: py, class: v === yd.lo ? "baseline" : "gridline" }, s);
        const tg = svg("g", { class: "tick" }, s);
        text(tg, padL - 8, py + 4, tickFmt(v, yd.step), { "text-anchor": "end" });
      }
      cfg.categories.forEach((c, i) => text(s, x(i), H - 10, c.label, { "text-anchor": "middle", class: "rowlabel" }));
      for (const l of cfg.lines) {
        const d = l.values.map((v, i) => (i ? "L" : "M") + x(i) + "," + y(v)).join("");
        const p = svg("path", { d, class: "runline" }, s);
        tipAttrs(p, l.tip, l.name);
        p.removeAttribute("tabindex");
      }
      for (const l of cfg.lines) {
        l.values.forEach((v, i) => {
          const c = svg("circle", { cx: x(i), cy: y(v), r: 4.5, fill: cfg.categories[i].color, class: "ring" }, s);
          tipAttrs(c, l.pointTips ? l.pointTips[i] : l.tip, l.name + " " + cfg.categories[i].label);
        });
      }
      if (cfg.yTitle) text(s, 0, 0, cfg.yTitle, { class: "axis-title", transform: `translate(11 ${(H - padB + padT) / 2}) rotate(-90)`, "text-anchor": "middle" });
    });
  }

  /* ---------- regime map, drawn as a timing diagram: one lane per condition (release arrow, open
   * waiting bar, solid service block, red overrun) against the deadline, next to the measured paired
   * difference. Tracing a lane (hover / focus) moves the dimension lines to it. ---------- */
  function regimeMap(container, cfg) {
    let played = false, wired = false;
    let live = null; // geometry and nodes of the current render, for the trace interaction
    const setTrace = (i) => {
      if (!live) return;
      live.dims.forEach((g, k) => g.classList.toggle("on", k === i));
      live.bands.forEach((g, k) => g.classList.toggle("on", k === i));
    };
    return mount(container, (el, W) => {
      const narrow = W < 720;
      const rows = cfg.rows, n = rows.length;
      const def = Math.max(0, rows.findIndex((r) => r.trace));
      const barH = 16, endW = 64, valueW = rows.some((r) => r.trace) ? (narrow ? 74 : 104) : (narrow ? 50 : 76);
      const rowH = narrow ? 92 : 64, barY = narrow ? 32 : 16, top = 46;
      const labelW = narrow ? 0 : Math.min(200, Math.max(...rows.map((r) => Math.max(measure(r.label, 13.5), measure(r.sub || "", 12)))) + 26);
      let lx0, lx1, dx0, dx1, dTop, dRowH;
      const lanesBottom = top + n * rowH;
      if (narrow) {
        lx0 = 6; lx1 = W - endW;
        dTop = lanesBottom + 64; dRowH = 40;
        dx0 = Math.min(W * 0.38, Math.max(...rows.map((r) => measure(r.label, 13))) + 16); dx1 = W - valueW;
      } else {
        const gap = 72, plotW = W - labelW - endW - gap - valueW;
        lx0 = labelW; lx1 = labelW + Math.round(plotW * 0.6);
        dx0 = lx1 + endW + gap; dx1 = W - valueW;
        dTop = top; dRowH = rowH;
      }
      const dBottom = dTop + n * dRowH, H = dBottom + 44;
      const tDom = niceDomain(0, Math.max(cfg.deadline * 1.15, ...rows.map((r) => r.age + r.service)), 6, { zero: true });
      const dv = [0];
      rows.forEach((r) => { dv.push(r.lo, r.hi, r.mean); (r.points || []).forEach((p) => dv.push(p.v)); });
      const dDom = niceDomain(Math.min(...dv.filter(isFinite)), Math.max(...dv.filter(isFinite)), narrow ? 3 : 4, { zero: true });
      const xt = lin(0, tDom.hi, lx0, lx1), xd = lin(dDom.lo, dDom.hi, dx0, dx1);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "group", "aria-label": cfg.ariaLabel || "" }, el);
      const bandLayer = svg("g", null, s);
      // lane hit areas sit under every mark, in row order, so Tab and the arrow keys walk the lanes top to bottom
      const hitLayer = svg("g", null, s);
      // the time ruler runs across the top of the lanes; gridlines drop from it
      const rY = 18;
      svg("line", { x1: lx0, x2: lx1, y1: rY + 0.5, y2: rY + 0.5, class: "ruler" }, s);
      const minor = tDom.step / 4;
      for (let v = 0; v <= tDom.hi + 1e-9; v += minor) {
        const px = Math.round(xt(v)) + 0.5, major = Math.abs(v / tDom.step - Math.round(v / tDom.step)) < 1e-6;
        svg("line", { x1: px, x2: px, y1: rY, y2: rY + (major ? 8 : 4), class: "ruler" }, s);
        if (major) {
          svg("line", { x1: px, x2: px, y1: top - 6, y2: lanesBottom, class: "gridline" }, s);
          const last = v + tDom.step > tDom.hi + 1e-9;
          text(svg("g", { class: "tick" }, s), px, rY - 7, tickFmt(v, tDom.step), { "text-anchor": "middle" });
        }
      }
      // unit: the full axis title beside the ruler, or just "ms" at the right edge on narrow screens
      if (narrow) text(s, W, rY - 7, "ms", { class: "axis-title", "text-anchor": "end" });
      // (left of the ruler, in the label column: beside the last tick it read as "120 ms after publish")
      else if (cfg.tTitle) text(s, lx0 - 12, rY + 4, cfg.tTitle, { class: "axis-title", "text-anchor": "end" });
      xAxis(s, xd, dDom, dTop - 6, dBottom, { title: cfg.dTitle, zeroStrong: true, width: W });
      const pxd = xt(cfg.deadline);
      refMark(s, pxd, top - 7, narrow ? top : lanesBottom, cfg.deadlineLabel, narrow ? W : dx0 - 16);
      // narrow: lane labels run across the deadline, so its line breaks around each label row
      if (narrow) for (let i = 0; i < n; i++) svg("line", { x1: pxd, x2: pxd, y1: top + i * rowH + 24, y2: top + (i + 1) * rowH, class: "refline" }, s);
      if (cfg.dHead) text(s, narrow ? 0 : dx0, narrow ? dTop - 30 : rY - 5, cfg.dHead, { class: "rowlabel strong" });
      const lateFill = hatch(s, "hatch-late");
      if (cfg.betterLabel) {
        const z = xd(0), m = measure(cfg.betterLabel, 12);
        if (z - 6 - m >= (narrow ? 0 : dx0 - 36)) text(s, z - 6, dTop - 12, cfg.betterLabel, { class: "reflabel muted-label", "text-anchor": "end" });
        else if (z + 6 + m <= W) text(s, z + 6, dTop - 12, cfg.betterLabel, { class: "reflabel muted-label", "text-anchor": "start" });
      }
      const marks = svg("g", null, s); // everything the playhead draws
      const dims = [], bands = [];
      rows.forEach((r, i) => {
        const y0 = top + i * rowH, yc = y0 + barY + barH / 2, base = yc + barH / 2;
        const end = r.age + r.service, late = end > cfg.deadline;
        const sig = isFinite(r.lo) && isFinite(r.hi) && (r.lo > 0 || r.hi < 0);
        if (i) svg("line", { x1: 0, x2: narrow ? W : W, y1: y0 + 0.5, y2: y0 + 0.5, class: "rowrule" }, s);
        bands.push(svg("rect", { x: 0, y: y0 + 1, width: W, height: rowH - 1, class: "trace-band" + (i === def ? " on" : "") }, bandLayer));
        if (narrow) {
          text(s, 0, y0 + 17, r.label, { class: "rowlabel strong" });
          if (r.sub) text(s, measure(r.label, 13.5) + 10, y0 + 17, r.sub, { class: "sublabel" });
        } else {
          text(s, 0, yc - 1, r.label, { class: "rowlabel strong" });
          if (r.sub) text(s, 0, yc + 16, r.sub, { class: "sublabel" });
        }
        // the lane: release at 0, wait (open), service (solid), overrun (red), finish time
        svg("line", { x1: lx0, x2: lx1, y1: base + 0.5, y2: base + 0.5, class: "lane-base" }, s);
        const a1 = xt(r.age), b1 = xt(end), tip = yc - barH / 2 - (narrow ? 8 : 12);
        svg("line", { x1: lx0, x2: lx0, y1: base, y2: tip + 6, class: "release" }, marks);
        svg("path", { d: `M${lx0 - 4.5},${tip + 7}H${lx0 + 4.5}L${lx0},${tip}Z`, class: "release", "stroke-width": 0 }, marks);
        if (r.age > 0) svg("rect", { x: lx0 + 0.75, y: yc - barH / 2 + 0.75, width: Math.max(0, a1 - lx0 - 1.5), height: barH - 1.5, class: "wait" }, marks);
        svg("path", { d: barPath(a1, Math.min(b1, pxd), yc - barH / 2, barH), class: "svc" }, marks);
        if (late) svg("rect", { x: pxd + 0.75, y: yc - barH / 2 + 0.75, width: Math.max(0, b1 - pxd - 1.5), height: barH - 1.5, class: "overshoot", fill: lateFill }, marks);
        text(marks, b1 + 8, yc + 4.5, `${fmt(end, 0)} ms`, { class: "vlabel strong" + (late ? " late" : "") });
        // dimension lines under the lane, shown for the traced lane only
        const dg = svg("g", { class: "dims" + (i === def ? " on" : "") }, marks), dy = base + 10;
        const dim = (va, vb, word) => {
          const xa = xt(va), xb = xt(vb), full = `${fmt(vb - va, 0)} ms ${word}`;
          svg("line", { x1: xa, x2: xb, y1: dy + 0.5, y2: dy + 0.5, class: "dim-line" }, dg);
          for (const px of [xa, xb]) svg("line", { x1: Math.round(px) + 0.5, x2: Math.round(px) + 0.5, y1: dy - 4, y2: dy + 5, class: "dim-line" }, dg);
          text(dg, (xa + xb) / 2, dy + 17, xb - xa >= measure(full, 12) + 6 ? full : fmt(vb - va, 0), { class: "dim-text", "text-anchor": "middle" });
        };
        if (r.age > 0) dim(0, r.age, cfg.waitWord || "wait");
        dim(r.age, end, cfg.serviceWord || "service");
        dims.push(dg);
        // paired difference: 95% interval, single blocks, mean
        const yd = narrow ? dTop + i * dRowH + dRowH / 2 : yc;
        if (narrow) {
          if (i) svg("line", { x1: 0, x2: W, y1: dTop + i * dRowH + 0.5, y2: dTop + i * dRowH + 0.5, class: "rowrule" }, s);
          text(s, 0, yd + 4, r.label, { class: "rowlabel" });
        }
        if (isFinite(r.lo) && isFinite(r.hi)) {
          const stroke = sig ? "var(--ink)" : "var(--muted)";
          svg("line", { x1: xd(r.lo), x2: xd(r.hi), y1: yd, y2: yd, stroke, "stroke-width": 2 }, s);
          for (const v of [r.lo, r.hi]) svg("line", { x1: xd(v), x2: xd(v), y1: yd - 5, y2: yd + 5, stroke, "stroke-width": 1.5 }, s);
        }
        (r.points || []).slice().sort((a, b) => a.v - b.v).forEach((p, k) => {
          const c = svg("circle", { cx: xd(p.v), cy: yd, r: 3.4, stroke: r.color, class: "blockdot", "data-row": i, "data-col": k + 1 }, s);
          tipAttrs(c, p.tip, p.label);
          c.addEventListener("focus", () => setTrace(i));
          c.addEventListener("blur", () => setTrace(def));
        });
        svg("circle", { cx: xd(r.mean), cy: yd, r: 5.5, fill: sig ? r.color : "var(--surface)", stroke: sig ? "var(--surface)" : r.color, "stroke-width": sig ? 2 : 1.75 }, s);
        // A zero-width interval at 0 means neither policy missed a frame, not "no effect": say so in place.
        if (r.zeroNote && r.lo === 0 && r.hi === 0) {
          if (narrow) text(s, 0, yd + 17, r.zeroNote, { class: "sublabel" });
          else text(s, xd(0) - 10, yd + 4, r.zeroNote, { class: "sublabel", "text-anchor": "end" });
        }
        // The traced lane's difference is the page's answer: set it large, with its interval under it.
        if (r.trace) {
          text(s, W, yd + (narrow ? 0 : 3), r.valueText + (cfg.unit || ""), { "text-anchor": "end", class: "vlabel " + (narrow ? "strong" : "lead") });
          text(s, W, yd + (narrow ? 15 : 19), `[${fmt(r.lo, 1)}, ${fmt(r.hi, 1)}]`, { "text-anchor": "end", class: "sublabel" });
        } else text(s, W, yd + 4.5, r.valueText + (narrow || !cfg.unit ? "" : cfg.unit), { "text-anchor": "end", class: "vlabel" + (sig ? " strong" : " dim") });
        const hit = svg("rect", { x: 0, y: y0, width: W, height: rowH, class: "hit", "data-row": i, "data-col": 0, "data-tip-x": (lx0 / W).toFixed(3) }, hitLayer);
        tipAttrs(hit, r.tip, r.label);
        // Hovering a lane already traces it and every number is drawn; the tooltip would only cover
        // the neighbouring lanes, so it appears for keyboard focus only.
        hit.setAttribute("data-tip-hover", "off");
        if (i === def) hit.setAttribute("data-entry", "");
        hit.addEventListener("focus", () => setTrace(i));
        hit.addEventListener("blur", () => setTrace(def));
      });
      live = { dims, bands, def, top, rowH, n, W };
      if (!wired) {
        wired = true;
        el.addEventListener("pointermove", (e) => {
          const box = el.getBoundingClientRect(), k = live.W / Math.max(1, box.width);
          const i = Math.floor(((e.clientY - box.top) * k - live.top) / live.rowH);
          setTrace(i >= 0 && i < live.n ? i : live.def);
        });
        el.addEventListener("pointerleave", () => setTrace(live.def));
      }
      // First render only: a playhead draws the lanes along the time axis. The finished figure is
      // the default; a timer guarantees it even when animation frames are paused (background tab).
      if (cfg.sweep && !played && !reduceMotion()) {
        played = true;
        const id = `sweep${++uid}`;
        const cr = svg("rect", { x: lx0 - 8, y: 0, width: 0, height: H }, svg("clipPath", { id }, svg("defs", null, s)));
        marks.setAttribute("clip-path", `url(#${id})`);
        const head = svg("line", { class: "playhead", x1: lx0, x2: lx0, y1: top - 8, y2: lanesBottom }, s);
        const full = lx1 + endW + 16 - (lx0 - 8), t0 = performance.now(), dur = 1200;
        let done = false;
        const finish = () => { if (done) return; done = true; marks.removeAttribute("clip-path"); head.remove(); };
        const step = (now) => {
          if (done || !cr.isConnected) return;
          const p = Math.min(1, Math.max(0, (now - t0) / dur)), e = 1 - Math.pow(1 - p, 4);
          cr.setAttribute("width", full * e);
          const hx = lx0 - 8 + full * e;
          if (hx >= lx1) head.remove(); else { head.setAttribute("x1", hx); head.setAttribute("x2", hx); }
          if (p < 1) requestAnimationFrame(step); else finish();
        };
        requestAnimationFrame(step);
        setTimeout(finish, dur + 500);
      }
    });
  }

  /* ---------- small CI strip for a single estimate ---------- */
  function ciStrip(container, est, opts) {
    opts = opts || {};
    return mount(container, (el, W) => {
      const H = 46;
      const dom = niceDomain(Math.min(est.lo, est.mean, 0, opts.min !== undefined ? opts.min : 0), Math.max(est.hi, est.mean, 0), 4, { zero: true });
      const x = lin(dom.lo, dom.hi, 16, W - 16);
      const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "ci-strip", role: "img", "aria-label": opts.label || "" }, el);
      for (const v of dom.ticks) {
        const px = Math.round(x(v)) + 0.5;
        svg("line", { x1: px, x2: px, y1: 4, y2: 24, class: v === 0 ? "zero" : "gridline" }, s);
        const tg = svg("g", { class: "tick" }, s);
        text(tg, px, 40, tickFmt(v, dom.step), { "text-anchor": "middle" });
      }
      svg("line", { x1: x(est.lo), x2: x(est.hi), y1: 14, y2: 14, stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "butt" }, s);
      for (const v of [est.lo, est.hi]) svg("line", { x1: x(v), x2: x(v), y1: 9, y2: 19, stroke: "var(--ink)", "stroke-width": 1.5 }, s);
      const c = svg("circle", { cx: x(est.mean), cy: 14, r: 5.5, fill: opts.color || "var(--ink)", class: "ring" }, s);
      tipAttrs(c, opts.tip, opts.label);
    });
  }

  window.Charts = { dotRows, forest, lineChart, hbars, slope, regimeMap, ciStrip, fmt, esc, refreshVisible };
})();
