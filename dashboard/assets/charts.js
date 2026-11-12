/* Minimal SVG chart primitives for the dashboard. No dependencies.
 * Every mark that carries data has a data-tip (HTML) shown on hover / keyboard focus. */
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
  function measure(str, size) { return String(str).length * (size || 12.5) * 0.56; }
  function refLabel(s, px, y, label, W) {
    const right = px + 4 + measure(label, 11.5) <= W;
    return text(s, right ? px + 4 : px - 4, y, label, { class: "reflabel", "text-anchor": right ? "start" : "end" });
  }
  function width(container) { return Math.max(280, Math.floor(container.clientWidth || 640)); }

  function tipAttrs(node, html, label) {
    if (!html) return;
    node.setAttribute("data-tip", html);
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "img");
    if (label) node.setAttribute("aria-label", label);
  }

  /* ---------- tooltip ---------- */
  let tipEl = null;
  function ensureTip() {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "tooltip";
      tipEl.setAttribute("role", "status");
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
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (t) show(t, e.clientX, e.clientY); else hide();
  });
  document.addEventListener("pointermove", (e) => {
    if (tipEl && tipEl.classList.contains("on")) place(e.clientX, e.clientY);
  });
  // Keyboard focus scrolls the mark into view; keep its tooltip attached instead of hiding it.
  let focusTip = null;
  document.addEventListener("focusin", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    focusTip = t || null;
    if (t) { const r = t.getBoundingClientRect(); show(t, r.right, r.top); } else hide();
  });
  document.addEventListener("focusout", () => { focusTip = null; hide(); });
  window.addEventListener("scroll", () => {
    if (focusTip && focusTip.isConnected) { const r = focusTip.getBoundingClientRect(); place(r.right, r.top); } else hide();
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
        svg("rect", { x: b0, y: top - 4, width: Math.max(2, b1 - b0), height: plotBottom - top + 4, class: "band", rx: 3 }, s);
        if (cfg.band.label) {
          const right = b0 + measure(cfg.band.label, 11) <= W;
          text(s, right ? b0 : b1, top - 10, cfg.band.label, { class: "bandlabel", "text-anchor": right ? "start" : "end" });
        }
      }
      xAxis(s, x, dom, top - 4, plotBottom, { title: cfg.xTitle, zeroStrong: true, width: W });
      for (const ref of cfg.refs || []) {
        const px = x(ref.value);
        svg("line", { x1: px, x2: px, y1: top - 8, y2: plotBottom, class: "refline" }, s);
        refLabel(s, px, top - 10, ref.label, W);
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
          if ((r.points || []).length) svg("line", { x1: x(r.mean), x2: x(r.mean), y1: y - 9, y2: y + 9, stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, s);
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
          svg("line", { x1: x(r.lo), x2: x(r.hi), y1: yc, y2: yc, stroke: r.dim ? "var(--muted)" : "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, s);
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
      for (const r of cfg.refs || []) {
        if (r.y !== undefined) {
          svg("line", { x1: padL, x2: W - padR, y1: y(r.y), y2: y(r.y), class: "refline" }, s);
          text(s, padL + 6, y(r.y) - 5, r.label, { class: "reflabel" });
        } else {
          svg("line", { x1: x(r.x), x2: x(r.x), y1: padT, y2: H - padB, class: "refline" }, s);
          refLabel(s, x(r.x) + 1, padT + 10, r.label, W - padR);
        }
      }
      const ends = [];
      for (const sr of cfg.series) {
        const pts = sr.points.slice().sort((a, b) => a.x - b.x);
        if (!cfg.scatter && pts.length > 1) {
          svg("path", { d: pts.map((p, i) => (i ? "L" : "M") + x(p.x).toFixed(1) + "," + y(p.y).toFixed(1)).join(""), fill: "none", stroke: sr.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
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
      ends.forEach((e) => text(s, e.x, e.y, e.name, { class: "vlabel" }));
      if (cfg.yTitle) {
        const t = text(s, 0, 0, cfg.yTitle, { class: "axis-title", transform: `translate(11 ${(H - padB + padT) / 2}) rotate(-90)`, "text-anchor": "middle" });
        t.setAttribute("x", 0);
      }
    });
  }

  /* ---------- horizontal (stacked) bars ---------- */
  function barPath(x0, x1, y, h, roundEnd) {
    const r = Math.min(4, Math.max(0, (x1 - x0) / 2), h / 2);
    if (!roundEnd || r <= 0) return `M${x0},${y}H${x1}V${y + h}H${x0}Z`;
    return `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 - r},${y + h}H${x0}Z`;
  }
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
      xAxis(s, x, dom, top - 4, plotBottom, { title: cfg.xTitle, width: W });
      for (const item of layout) {
        if (item.group) { groupLabel(s, item.y + 17, item.group); continue; }
        const r = item.row, y = item.y;
        text(s, 0, y + 4, r.label, { class: "rowlabel" + (r.dim ? " dim" : "") });
        let acc = 0;
        const segs = r.segments.filter((sg) => (sg.v || 0) > 0);
        segs.forEach((sg, i) => {
          const a = x(acc), b = x(acc + sg.v);
          const gap = i < segs.length - 1 ? 2 : 0;
          if (b - a - gap > 0.5) {
            const p = svg("path", { d: barPath(a, b - gap, y - barH / 2, barH, i === segs.length - 1), fill: sg.color }, s);
            tipAttrs(p, sg.tip || r.tip, r.label + " " + (sg.name || ""));
          }
          acc += sg.v;
        });
        const endX = Math.max(x(acc), r.marker !== undefined && r.marker !== null ? x(r.marker) : 0);
        let vt = r.valueText !== undefined ? r.valueText : fmt(acc, cfg.nd);
        if (r.valueNote && endX + 7 + measure(vt + " · " + r.valueNote, 12) <= W) vt += " · " + r.valueNote;
        text(s, endX + 7, y + 4, vt, { class: "vlabel" + (r.dim ? " dim" : "") });
        if (r.marker !== undefined && r.marker !== null) {
          svg("line", { x1: x(r.marker), x2: x(r.marker), y1: y - barH / 2 - 4, y2: y + barH / 2 + 4, stroke: "var(--ink)", "stroke-width": 2 }, s);
        }
      }
      for (const ref of cfg.refs || []) {
        const px = x(ref.value);
        svg("line", { x1: px, x2: px, y1: top - 8, y2: plotBottom, class: "refline" }, s);
        refLabel(s, px, top - 10, ref.label, W);
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
      svg("line", { x1: x(est.lo), x2: x(est.hi), y1: 14, y2: 14, stroke: "var(--ink)", "stroke-width": 2, "stroke-linecap": "round" }, s);
      for (const v of [est.lo, est.hi]) svg("line", { x1: x(v), x2: x(v), y1: 9, y2: 19, stroke: "var(--ink)", "stroke-width": 1.5 }, s);
      const c = svg("circle", { cx: x(est.mean), cy: 14, r: 5.5, fill: opts.color || "var(--ink)", class: "ring" }, s);
      tipAttrs(c, opts.tip, opts.label);
    });
  }

  window.Charts = { dotRows, forest, lineChart, hbars, slope, ciStrip, fmt, esc, refreshVisible };
})();
