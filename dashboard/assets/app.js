/* Dashboard core: data check, lookups, hash routing. Each view lives in assets/views/<view>.js and
 * registers itself on window.Dash.views. All numbers come from window.DASHBOARD_DATA
 * (src/dashboard/build_data.py). Text is written as L(english, traditional_chinese); see assets/i18n.js. */
(function () {
  "use strict";
  const D = window.DASHBOARD_DATA;
  const C = window.Charts;
  const UI = window.UI;
  const { fmt, esc } = C;
  const L = (window.I18N && window.I18N.L) || ((en) => en);
  // Bundle text field in the current language: "<key>_zh" when Chinese is on and the builder wrote it.
  const T = (o, k) => (window.I18N && window.I18N.zh && o[k + "_zh"]) || o[k];
  const main = document.getElementById("main");

  if (!D || D.schema !== "dashboard_data/v1") {
    main.innerHTML = L(`<div class="empty-state"><h2>Dashboard data not found</h2>
      <p>Expected <code>dashboard/data/dashboard_data.js</code> (schema <code>dashboard_data/v1</code>).</p>
      <p>Build it from the verified result tables:</p>
      <pre class="cmd">python3 -m src.dashboard.build_data</pre>
      <p class="muted small">The builder refuses to write anything if a source file is missing (BLOCKED) or no longer matches its SHA-256 manifest (BROKEN).</p></div>`,
    `<div class="empty-state"><h2>找不到 Dashboard 資料</h2>
      <p>需要 <code>dashboard/data/dashboard_data.js</code>（schema <code>dashboard_data/v1</code>）。</p>
      <p>請從已驗證的結果表格建置：</p>
      <pre class="cmd">python3 -m src.dashboard.build_data</pre>
      <p class="muted small">只要有來源檔缺少（BLOCKED）或與 SHA-256 manifest 不符（BROKEN），builder 就不會寫出任何檔案。</p></div>`);
    return;
  }

  /* ---------- lookups ---------- */
  // Colour belongs to the three compared policies; FIFO and the legacy arms are drawn in greys.
  const ARM = {}; D.arms.forEach((a) => { ARM[a.id] = Object.assign({ color: a.slot <= 3 ? `var(--s${a.slot})` : `var(--arm-${a.slot})` }, a); });
  const S = D.scheduling;
  const COND = {}; S.conditions.forEach((c) => { COND[c.id] = c; });
  const MODEL = { mobilevit_s: "MobileViT-S", mobilevit_xxs: "MobileViT-XXS" };
  const MODEL_COLOR = { mobilevit_s: "var(--model-s)", mobilevit_xxs: "var(--model-xxs)" }; // never arm colours
  const APP_ORDER = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10", "fifo_c5_q10"];
  const LEGACY_ORDER = ["legacy_q1", "legacy_q5"];
  const METRICS = {
    effective_miss_rate_pct: { label: "Effective miss", unit: "%", d: " pp", nd: 1, dnd: 2, better: "lower", axis: L("Effective miss (%) — dropped + late frames / published", "Effective miss (%) — (dropped + late frames) / published") },
    on_time_fps: { label: "On-time FPS", unit: " FPS", d: " FPS", nd: 2, dnd: 2, better: "higher", axis: L("On-time throughput (frames/s within 100 ms)", "On-time throughput（100 ms 內完成的 frames/s）") },
    p99_latency_ms: { label: "P99 latency", unit: " ms", d: " ms", nd: 1, dnd: 1, better: "lower", axis: L("P99 end-to-end latency of processed frames (ms)", "Processed frames 的 P99 end-to-end latency (ms)") },
  };
  const betterText = (M) => (M.better === "lower" ? L("lower is better", "越低越好") : L("higher is better", "越高越好"));
  const armRow = (cid, arm) => S.arms_table.find((r) => r.condition === cid && r.arm === arm);
  const pairRow = (cid, arm, ref) => S.paired.find((r) => r.condition === cid && r.arm === arm && r.reference === ref);
  const runsOf = (cid, arm) => S.runs.filter((r) => r.condition === cid && r.arm === arm);
  const blockNo = (tag) => (tag.match(/_b(\d+)$/) || [])[1] || tag;
  const ci = (e, nd) => `[${fmt(e.lo, nd)}, ${fmt(e.hi, nd)}]`;
  const { tipRows } = UI;
  // The space before the badge keeps the accessible name "S · 20 FPS primary", not "…FPSprimary".
  const condOptions = (keep) => S.conditions.filter(keep || (() => true)).map((c) => ({ value: c.id, label: c.label, html: esc(c.label) + (c.primary ? ` <span class="star" title="${L("primary condition, fixed in the analysis plan before the formal runs", "primary condition，正式 run 之前已在分析計畫中固定")}">${L("primary", "主要")}</span>` : "") }));
  const MEAS = `<span class="tag measured">${L("Measured", "實測")}</span>`;

  // Per-block differences for display only. They are drawn only when their mean reproduces the
  // reported paired estimate (built from the same runs), so the dots can never disagree with the KPI.
  function blockDiffs(cid, arm, ref, metric, est, nBlocks, nd, unit) {
    const a = runsOf(cid, arm), b = runsOf(cid, ref);
    const pts = [];
    a.forEach((ra) => {
      const rb = b.find((x) => x.block === ra.block);
      if (rb && isFinite(ra[metric]) && isFinite(rb[metric])) pts.push({ block: ra.block, v: ra[metric] - rb[metric] });
    });
    if (!est || pts.length !== nBlocks) return [];
    const mean = pts.reduce((s, p) => s + p.v, 0) / pts.length;
    if (Math.abs(mean - est.mean) > 0.0051 + Math.abs(est.mean) * 1e-3) return [];
    // The condition is part of every label: a block dot heard on its own must still say where it belongs.
    return pts.map((p) => ({ v: p.v, label: `${COND[cid].label} · block ${blockNo(p.block)}`,
      tip: tipRows(`${ARM[arm].label} − ${ARM[ref].label} · ${COND[cid].label} · block ${blockNo(p.block)}`, [["Δ", fmt(p.v, nd, true) + unit]]) }));
  }

  /* ---------- routing & state ---------- */
  const VIEWS = ["overview", "baseline", "scheduling", "mechanism", "evidence"];
  const TITLE = { baseline: L("Baseline", "基準測試"), scheduling: L("Scheduling", "排程比較"), mechanism: L("Mechanism", "運作機制"), evidence: L("Evidence", "驗證證據") };
  const state = { c: D.primary_condition, m: "effective_miss_rate_pct", model: "both", mc: D.primary_condition };
  const views = {};
  const rendered = {};
  let shownView = null; // the view on screen before this route() call (null on first load)
  let anchor = null;    // optional panel inside the view: #evidence/limitations → #evidence-limitations
  let unknown = null;   // a hash that names no view (shown as a note above the overview)
  function parseHash() {
    const raw = (location.hash || "#overview").slice(1);
    const [path, q] = raw.split("?");
    const [view, sub] = path.split("/");
    anchor = sub || null;
    unknown = view && !VIEWS.includes(view) && view !== "main" ? view : null;
    const params = new URLSearchParams(q || "");
    if (params.get("c") && COND[params.get("c")]) state.c = params.get("c");
    if (params.get("mc") && COND[params.get("mc")] && !COND[params.get("mc")].dynamic) state.mc = params.get("mc");
    if (params.get("m") && METRICS[params.get("m")]) state.m = params.get("m");
    if (params.get("model") && ["both", "mobilevit_s", "mobilevit_xxs"].includes(params.get("model"))) state.model = params.get("model");
    return VIEWS.includes(view) ? view : "overview";
  }
  function setParams(view, params) {
    const q = new URLSearchParams(params).toString();
    history.replaceState(null, "", `#${view}${q ? "?" + q : ""}`);
  }
  // The selection a view keeps between visits, written back into the URL so a copied link shows
  // what is on screen (a nav link is a bare #view). Defaults are left out to keep links short.
  function viewParams(view) {
    const p = {};
    if (view === "scheduling") { if (state.c !== D.primary_condition) p.c = state.c; if (state.m !== "effective_miss_rate_pct") p.m = state.m; }
    if (view === "mechanism" && state.mc !== D.primary_condition) p.mc = state.mc;
    if (view === "baseline" && state.model !== "both") p.model = state.model;
    return p;
  }
  function routeNote() {
    let n = document.getElementById("route-note");
    if (!unknown) { if (n) n.remove(); return; }
    if (!n) { n = document.createElement("div"); n.id = "route-note"; n.className = "callout"; n.setAttribute("role", "status"); main.prepend(n); }
    n.innerHTML = L(`<p>There is no section called <code>#${esc(unknown)}</code>, so this is the overview. The sections are Overview, Baseline, Scheduling, Mechanism and Evidence.</p>`,
      `<p>沒有名為 <code>#${esc(unknown)}</code> 的分頁，因此顯示總覽。分頁包括總覽、基準測試、排程比較、運作機制與驗證證據。</p>`);
  }
  function route() {
    const view = parseHash();
    document.querySelectorAll(".nav a[data-view]").forEach((a) => {
      if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.querySelectorAll("section.view").forEach((sec) => { sec.hidden = sec.dataset.view !== view; });
    const sec = document.getElementById("view-" + view);
    if (!rendered[view]) { views[view](sec); rendered[view] = true; } else C.refreshVisible();
    // A new view starts at its own heading: without this the page keeps the previous view's scroll
    // offset and keyboard / screen-reader focus stays on the nav link. Parameter-only changes use
    // replaceState (no hashchange), so the controls never jump the page.
    const target = anchor && document.getElementById(`${view}-${anchor}`);
    if (target) { target.scrollIntoView({ block: "start" }); if (shownView !== null) focusHeading(target.querySelector("h2, h3")); }
    else if (shownView !== null && shownView !== view) { window.scrollTo(0, 0); focusHeading(sec.querySelector("h2")); }
    if (!anchor && !unknown) { const p = viewParams(view); if (Object.keys(p).length) setParams(view, p); }
    routeNote();
    shownView = view;
    document.title = (TITLE[view] ? TITLE[view] + " · " : "") + "OS-Aware Edge AI Runtime";
  }
  function focusHeading(h) {
    if (!h) return;
    h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
  }
  window.addEventListener("hashchange", () => { Object.keys(rendered).forEach((k) => { if (k !== "overview" && k !== "evidence") rendered[k] = false; }); route(); });

  window.Dash = Object.assign({ D, C, L, T, fmt, esc, S, ARM, COND, MODEL, MODEL_COLOR, APP_ORDER, LEGACY_ORDER, METRICS, betterText,
    armRow, pairRow, runsOf, blockNo, ci, blockDiffs, condOptions, MEAS, state, setParams, views }, UI);
  // The view scripts load after this file; the first route runs once they have all registered.
  document.addEventListener("DOMContentLoaded", route);
})();
