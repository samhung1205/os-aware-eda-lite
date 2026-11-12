/* Dashboard views. All numbers come from window.DASHBOARD_DATA (src/dashboard/build_data.py). */
(function () {
  "use strict";
  const D = window.DASHBOARD_DATA;
  const C = window.Charts;
  const { fmt, esc } = C;
  const main = document.getElementById("main");

  if (!D || D.schema !== "dashboard_data/v1") {
    main.innerHTML = `<div class="empty-state"><h2>Dashboard data not found</h2>
      <p>Expected <code>dashboard/data/dashboard_data.js</code> (schema <code>dashboard_data/v1</code>).</p>
      <p>Build it from the verified result tables:</p>
      <pre class="cmd">python3 -m src.dashboard.build_data</pre>
      <p class="muted small">The builder refuses to write anything if a source file is missing (BLOCKED) or no longer matches its SHA-256 manifest (BROKEN).</p></div>`;
    return;
  }

  /* ---------- lookups ---------- */
  const ARM = {}; D.arms.forEach((a) => { ARM[a.id] = Object.assign({ color: `var(--s${a.slot})` }, a); });
  const S = D.scheduling;
  const COND = {}; S.conditions.forEach((c) => { COND[c.id] = c; });
  const MODEL = { mobilevit_s: "MobileViT-S", mobilevit_xxs: "MobileViT-XXS" };
  const MODEL_COLOR = { mobilevit_s: "var(--s1)", mobilevit_xxs: "var(--s2)" };
  const APP_ORDER = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10", "fifo_c5_q10"];
  const LEGACY_ORDER = ["legacy_q1", "legacy_q5"];
  const METRICS = {
    effective_miss_rate_pct: { label: "Effective miss", unit: "%", d: " pp", nd: 1, dnd: 2, better: "lower", axis: "Effective miss (%) — dropped + late frames / published" },
    on_time_fps: { label: "On-time FPS", unit: " FPS", d: " FPS", nd: 2, dnd: 2, better: "higher", axis: "On-time throughput (frames/s within 100 ms)" },
    p99_latency_ms: { label: "P99 latency", unit: " ms", d: " ms", nd: 1, dnd: 1, better: "lower", axis: "P99 end-to-end latency of processed frames (ms)" },
  };
  const armRow = (cid, arm) => S.arms_table.find((r) => r.condition === cid && r.arm === arm);
  const pairRow = (cid, arm, ref) => S.paired.find((r) => r.condition === cid && r.arm === arm && r.reference === ref);
  const runsOf = (cid, arm) => S.runs.filter((r) => r.condition === cid && r.arm === arm);
  const blockNo = (tag) => (tag.match(/_b(\d+)$/) || [])[1] || tag;
  const ci = (e, nd) => `[${fmt(e.lo, nd)}, ${fmt(e.hi, nd)}]`;
  const tipRows = (title, rows) => `<b>${esc(title)}</b>` + rows.map(([k, v]) => `<div class="row"><span>${esc(k)}</span><span>${v}</span></div>`).join("");
  const sw = (color) => `<span class="sw" style="background:${color}"></span>`;

  /* ---------- routing & state ---------- */
  const VIEWS = ["overview", "baseline", "scheduling", "mechanism", "evidence"];
  const state = { c: D.primary_condition, m: "effective_miss_rate_pct", model: "both", mc: D.primary_condition };
  const rendered = {};
  function parseHash() {
    const raw = (location.hash || "#overview").slice(1);
    const [view, q] = raw.split("?");
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
  function route() {
    const view = parseHash();
    document.querySelectorAll(".nav a[data-view]").forEach((a) => {
      if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.querySelectorAll("section.view").forEach((sec) => { sec.hidden = sec.dataset.view !== view; });
    const sec = document.getElementById("view-" + view);
    if (!rendered[view]) { RENDER[view](sec); rendered[view] = true; } else C.refreshVisible();
    document.title = { overview: "OS-Aware Edge AI Runtime", baseline: "Baseline · OS-Aware Edge AI Runtime", scheduling: "Scheduling · OS-Aware Edge AI Runtime", mechanism: "Mechanism · OS-Aware Edge AI Runtime", evidence: "Evidence · OS-Aware Edge AI Runtime" }[view];
  }
  window.addEventListener("hashchange", () => { Object.keys(rendered).forEach((k) => { if (k !== "overview" && k !== "evidence") rendered[k] = false; }); route(); });

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
    return wrap;
  }
  function control(container, label, segEl) {
    const span = document.createElement("div");
    span.className = "control";
    span.innerHTML = `<span class="control-label">${esc(label)}</span>`;
    span.appendChild(segEl); container.appendChild(span);
  }
  function table(headers, rows, opts) {
    opts = opts || {};
    const th = headers.map((h) => `<th class="${h.l ? "l" : ""} ${h.wrap ? "wrap" : ""}">${h.html || esc(h.label)}</th>`).join("");
    const tr = rows.map((r) => `<tr class="${r.hl ? "hl" : ""}">${r.cells.map((c, i) => `<td class="${headers[i] && headers[i].l ? "l" : ""} ${headers[i] && headers[i].wrap ? "wrap" : ""}">${c}</td>`).join("")}</tr>`).join("");
    const t = `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
    return opts.toggle ? `<details class="table-toggle"${opts.open ? " open" : ""}><summary>${esc(opts.toggle)}</summary>${t}</details>` : t;
  }
  const condOptions = () => S.conditions.map((c) => ({ value: c.id, label: c.label, html: esc(c.label) + (c.primary ? '<span class="star" title="primary condition, fixed in the analysis plan before the formal runs">primary</span>' : "") }));

  /* =============================== OVERVIEW =============================== */
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
    return pts.map((p) => ({ v: p.v, label: `block ${blockNo(p.block)}`,
      tip: tipRows(`${ARM[arm].label} − ${ARM[ref].label} · block ${blockNo(p.block)}`, [["Δ", fmt(p.v, nd, true) + unit]]) }));
  }

  function renderOverview(sec) {
    const K = D.kpis;
    const g = K.guard_vs_latest_primary, ag = K.adaptive_vs_guard_primary, al = K.adaptive_vs_latest_primary;
    const gd = K.guard_vs_latest_dynamic, agd = K.adaptive_vs_guard_dynamic;
    const pc = COND[D.primary_condition];
    const cap = K.capacity;
    const F = {}; D.findings.forEach((f) => { F[f.id] = f; });
    const chain = (D.baseline.chain_records_verified || 0) + (S.chain_records_verified || 0);
    const lat = armRow(pc.id, "latest_q10"), grd = armRow(pc.id, "guard_c5_q10"), ada = armRow(pc.id, "adaptive_c5_q10");
    sec.innerHTML = `
      <div class="hero">
        <div>
          <h2>Which frames should an overloaded edge detector skip?</h2>
          <p class="lede">A measured ROS 2 benchmark of frame-scheduling policies for a MobileViT detector on a constrained Linux host: two pinned CPU cores, a 4 GiB memory limit and a Fast DDS shared-memory transport verified on every run.</p>
          <p class="answer">Skipping frames that are predicted to miss the ${fmt(pc.deadline_ms, 0)} ms deadline (<b>Deadline-Guard</b>) lowers the effective miss rate by <b>${fmt(-g.mean, 1)} pp</b> against Latest-Frame at ${esc(pc.label)}. <b>Adaptive</b>, which adds a utilisation switch on top, lands in the same place: no measurable difference from Deadline-Guard.</p>
          <div class="links"><a href="#scheduling">Compare all six policies</a><a href="#mechanism">Why it works</a><a href="#evidence">How the data is verified</a></div>
        </div>
        <div class="panel hero-chart">
          <div class="result" aria-label="Main result">
            <p class="result-cap">Effective miss at ${esc(pc.label)} · ρ ≈ ${fmt(lat.utilization.mean, 2)} (overloaded) · ${fmt(pc.deadline_ms, 0)} ms deadline · lower is better</p>
            <div class="result-row">
              <div class="r-item"><span class="r-label">${sw(ARM.latest_q10.color)}Latest-Frame</span><span class="r-v">${fmt(lat.effective_miss_rate_pct.mean, 1)}%</span></div>
              <svg class="r-arrow" viewBox="0 0 40 16" aria-hidden="true"><path d="M2 8h33M29 3l6 5-6 5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <div class="r-item"><span class="r-label">${sw(ARM.guard_c5_q10.color)}Deadline-Guard</span><span class="r-v">${fmt(grd.effective_miss_rate_pct.mean, 1)}%</span></div>
              <div class="r-item r-peer"><span class="r-label">${sw(ARM.adaptive_c5_q10.color)}Adaptive</span><span class="r-v">${fmt(ada.effective_miss_rate_pct.mean, 1)}%</span></div>
            </div>
            <p class="r-diff"><b>${fmt(g.mean, 2)} pp</b> paired difference (Deadline-Guard − Latest-Frame) · 95% CI ${ci(g, 2)} · lower in ${g.n_neg} of ${g.n_blocks} blocks</p>
          </div>
          <hr class="fig-divider">
          <div class="fig-head"><div class="titles"><h3>Every run</h3>
            <p class="fig-sub">Dropped + late frames, % of published · same application architecture · ${pc.n_blocks} runs per policy</p></div></div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>one run</span><span class="k"><span class="sw tick"></span>mean</span></div>
          <div class="chart" id="hero-dots"></div>
          <hr class="fig-divider">
          <div class="fig-head"><div class="titles"><h3>Paired difference within blocks</h3>
            <p class="fig-sub">Mean and 95% interval over ${g.n_blocks} blocks · open circles are single blocks</p></div></div>
          <div class="chart" id="hero-forest"></div>
          <p class="fig-note">One host, n = ${g.n_blocks} blocks for this condition, latency only (random-initialised weights). Adaptive − Deadline-Guard includes 0, which is not an equivalence test. <a href="#evidence">Limitations</a></p>
        </div>
      </div>

      <div class="stat-row">
        <div class="stat"><div class="label">Adaptive − Latest-Frame · ${esc(pc.label)}</div><div class="v">${fmt(al.mean, 1)}<span class="unit">pp</span></div><div class="d">95% CI ${ci(al, 2)} · ${al.n_neg}/${al.n_blocks} blocks lower</div></div>
        ${gd ? `<div class="stat"><div class="label">Guard − Latest under a load step · ${esc(COND[gd.condition].label)}</div><div class="v">${fmt(gd.mean, 1)}<span class="unit">pp</span></div><div class="d">95% CI ${ci(gd, 2)} · Adaptive − Guard ${fmt(agd.mean, 2, true)} pp</div></div>` : ""}
        <div class="stat"><div class="label">Saturated throughput</div><div class="v">${fmt(cap.mobilevit_s.mean, 1)}<span class="unit">FPS (S)</span></div><div class="d">MobileViT-XXS ${fmt(cap.mobilevit_xxs.mean, 1)} FPS · overloaded runs, n=${cap.mobilevit_s.n_runs} / ${cap.mobilevit_xxs.n_runs}</div></div>
        <div class="stat"><div class="label">Constrained runs</div><div class="v">${K.runs.total}</div><div class="d">${K.runs.phase2} baseline + ${K.runs.phase3} A/B in ${K.runs.phase3_blocks} blocks · ${chain} file hashes verified</div></div>
      </div>

      <section class="section">
        <div class="section-head"><div><h3>The system</h3>
          <p>One detector, one worker, a bounded queue in front of it, and a policy that decides which frame runs next.</p></div></div>
        <div class="prose-cols">
          <div><h4>Problem</h4><p>MobileViT-S saturates at about ${fmt(cap.mobilevit_s.mean, 0)} FPS on two cores. When frames arrive faster, some must be skipped. Always running the newest frame can still spend inference time on frames that then finish after the ${fmt(pc.deadline_ms, 0)} ms deadline.</p></div>
          <div><h4>Approach</h4><p>FIFO, Latest-Frame, Deadline-Guard and Adaptive share one application queue and one inference worker, so differences between them are policy effects. Deadline-Guard predicts, before inference, whether a frame can still meet its deadline; Adaptive adds a utilisation switch.</p></div>
          <div><h4>Evidence</h4><p>Policies run interleaved in blocks under identical controls and are compared within each block. Every table on this site is rebuilt from raw per-frame logs and checked against SHA-256 manifests before the page is generated.</p></div>
        </div>
        <div class="panel arch-panel"><div class="arch-scroll"><a href="assets/architecture.svg" target="_blank" rel="noopener" class="arch-link" title="Open the full-size diagram">
          <img class="arch" src="assets/architecture.svg" alt="Architecture: image_stream_node publishes frames over Fast DDS shared memory to the MobileViT detector node. The legacy path runs inference in the DDS callback; the application path puts frames in a bounded queue served by one worker using FIFO, Latest-Frame, Deadline-Guard or Adaptive. Each run writes detector and publisher CSVs, metadata and a runtime probe; analysis tools build summaries and aggregates with SHA-256 manifests; provenance gates and the dashboard builder verify the chain. Separately, the EDA-Lite simulator turns simplified model profiles into cost-model estimates.">
        </a></div><p class="arch-open"><a href="assets/architecture.svg" target="_blank" rel="noopener">Open the full-size diagram</a><span class="arch-hint"> · or scroll sideways</span></p></div>
      </section>

      <section class="section">
        <div class="section-head"><div><h3>Findings</h3>
          <p>Each answer is generated from the result tables when the dashboard is built.</p></div></div>
        <div class="grid">
          <div class="span-7">
            <ol class="qlist">
              <li><div class="q">Where does the pipeline saturate, and why are frames lost?</div><div class="a">${esc(F.capacity.text)}</div></li>
              <li><div class="q">Which policy keeps the most frames inside a ${fmt(pc.deadline_ms, 0)} ms deadline under overload?</div><div class="a">${esc(F.guard.text)}</div></li>
              <li><div class="q">Does Adaptive's utilisation switch add anything beyond the deadline check?</div><div class="a">${esc(F.adaptive.text)}</div></li>
            </ol>
          </div>
          <div class="span-5">
            <ul class="findings" style="grid-template-columns:1fr">
              ${["regime", "dynamic"].filter((k) => F[k]).map((k) => `<li><div class="t">${esc(F[k].title)}</div><div class="x">${esc(F[k].text)}</div></li>`).join("")}
              <li><div class="t">Legacy comparisons are kept separate</div><div class="x">The legacy arms run inference inside the DDS callback, so differences against them mix architecture and policy and are never attributed to a policy. <a href="#scheduling">See paired differences</a></div></li>
            </ul>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="section-head"><div><h3>What the project contributes</h3></div></div>
        <ul class="contrib">
          <li><div class="t">Constrained ROS 2 benchmark harness <span class="tag measured">Measured</span></div><div class="x">CPU pinning, the memory limit and the shared-memory transport are read back from every run's metadata and runtime probe. ${K.runs.phase2} baseline runs map capacity, drops and queueing before any scheduling.</div></div></li>
          <li><div class="t">Deadline-feasibility scheduling with an ablation <span class="tag measured">Measured</span></div><div class="x">Four policies behind one bounded queue, plus two legacy arms, in ${K.runs.phase3} interleaved runs. Adaptive − Deadline-Guard isolates the utilisation switch.</div></div></li>
          <li><div class="t">Provenance-gated results</div><div class="x">Raw logs, tables and this dashboard are SHA-256 chained; pilot, unverified or example data stops the build. <a href="#evidence">Evidence</a></div></li>
          <li><div class="t">EDA-Lite layer-fusion simulator <span class="tag estimate">Estimates</span></div><div class="x">An offline cost model for simplified MobileViT profiles under SRAM budgets, in cost-model units and kept on its own page. Not linked to the runtime results. <a href="simulation.html">Simulation explorer</a></div></div></li>
        </ul>
      </section>`;

    const heroArms = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10"];
    C.dotRows(sec.querySelector("#hero-dots"), { valueW: 56, rowH: 32,
      rows: heroArms.map((id) => { const r = armRow(pc.id, id), st = r.effective_miss_rate_pct;
        return { label: ARM[id].label, color: ARM[id].color, mean: st.mean, min: st.min, max: st.max, valueText: fmt(st.mean, 1) + "%",
          points: runsOf(pc.id, id).map((x) => ({ v: x.effective_miss_rate_pct, label: `${ARM[id].label} block ${blockNo(x.block)}`,
            tip: tipRows(`${ARM[id].label} · block ${blockNo(x.block)}`, [["effective miss", fmt(x.effective_miss_rate_pct, 1) + "%"], ["drop", fmt(x.drop_rate_pct, 1) + "%"], ["late (of processed)", fmt(x.deadline_miss_rate_pct, 1) + "%"]]) })),
          tip: tipRows(`${ARM[id].label} · ${pc.label}`, [["mean ± SD", `${fmt(st.mean, 1)} ± ${fmt(st.sd, 1)}%`], ["min – max", `${fmt(st.min, 1)} – ${fmt(st.max, 1)}%`], ["runs", r.n_runs]]) }; }),
      xTitle: "Effective miss (%)", ariaLabel: "Effective miss for Latest-Frame, Deadline-Guard and Adaptive" });
    const heroPairs = [["guard_c5_q10", "latest_q10", g], ["adaptive_c5_q10", "guard_c5_q10", ag]];
    C.forest(sec.querySelector("#hero-forest"), {
      rows: heroPairs.map(([a, ref, e]) => ({ label: `${ARM[a].label} − ${ARM[ref].label}`, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM[a].color,
        sub: `${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${e.n_neg} of ${e.n_blocks} blocks lower`,
        points: blockDiffs(pc.id, a, ref, "effective_miss_rate_pct", e, e.n_blocks, 2, " pp"),
        tip: tipRows(`${ARM[a].label} − ${ARM[ref].label}`, [["mean Δ", fmt(e.mean, 2, true) + " pp"], ["95% t-interval", ci(e, 2)], ["blocks lower / higher", `${e.n_neg} / ${e.n_pos}`], ["sign-flip p", fmt(e.signflip_p, 3)]]) })),
      xTitle: "Δ effective miss (pp)", ariaLabel: "Paired differences: Guard minus Latest, Adaptive minus Guard" });
  }

  /* =============================== BASELINE =============================== */
  function renderBaseline(sec) {
    const B = D.baseline;
    const cap = B.capacity, dm = B.drop_model;
    sec.innerHTML = `
      <div class="view-head"><h2>Baseline Performance: Capacity, Queueing, and Overload</h2>
      <p>${B.n_runs} constrained runs over ${B.n_conditions} conditions (3 runs each): input rate, subscriber queue depth and injected service delay. Every run uses the legacy path (inference in the DDS callback).</p></div>
      <div class="controls" id="b-controls"></div>
      <div class="stat-row">
        <div class="stat"><div class="label">MobileViT-S saturated throughput</div><div class="v">${fmt(cap.mobilevit_s.mean, 1)}<span class="unit">FPS</span></div><div class="d">${fmt(cap.mobilevit_s.min, 1)}–${fmt(cap.mobilevit_s.max, 1)}, n=${cap.mobilevit_s.n_runs} runs · service ${fmt(cap.mobilevit_s.service_ms_mean, 1)} ms</div></div>
        <div class="stat"><div class="label">MobileViT-XXS saturated throughput</div><div class="v">${fmt(cap.mobilevit_xxs.mean, 1)}<span class="unit">FPS</span></div><div class="d">${fmt(cap.mobilevit_xxs.min, 1)}–${fmt(cap.mobilevit_xxs.max, 1)}, n=${cap.mobilevit_xxs.n_runs} runs · service ${fmt(cap.mobilevit_xxs.service_ms_mean, 1)} ms</div></div>
        <div class="stat"><div class="label">Worst drop rate below capacity (ρ &lt; 1)</div><div class="v">${fmt(dm.below_capacity_max_drop_pct, 2)}<span class="unit">%</span></div><div class="d">worst of ${dm.below_capacity_runs} runs with ρ &lt; 1: almost every frame was delivered and processed</div></div>
        <div class="stat"><div class="label">Overload drops vs 1 − 1/ρ</div><div class="v">${fmt(dm.overloaded_mean_abs_gap_pp, 2)}<span class="unit">pp mean gap</span></div><div class="d">max ${fmt(dm.overloaded_max_abs_gap_pp, 2)} pp over ${dm.overloaded_runs} overloaded runs</div></div>
      </div>
      <div class="grid section-gap">
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>Throughput saturates at the service-time limit</h3><p class="fig-sub">Processed vs offered FPS · input-rate sweep (depth 5, no delay) · mean of 3 runs</p></div></div><div class="legend" id="b1-legend"></div><div class="chart" id="b1"></div></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>Drops follow the overload model 1 − 1/ρ</h3><p class="fig-sub">Every baseline run · measured drop rate vs prediction from offered rate × service time</p></div></div><div class="legend" id="b2-legend"></div><div class="chart" id="b2"></div></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>Under overload, queue depth sets the latency</h3><p class="fig-sub">P50 end-to-end latency at 20 FPS by KEEP_LAST depth · bar = mean, tick = P99 · 3 runs each</p></div></div><div class="chart" id="b3"></div>
        <p class="fig-note">The single-threaded detector always serves the oldest of the <i>depth</i> frames DDS keeps, so queue wait ≈ depth / input rate once the detector is saturated.</p></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>Injected service delay pushes both models into overload</h3><p class="fig-sub">Effective miss vs artificial delay added to each inference · 20 FPS, depth 5</p></div></div><div class="legend" id="b4-legend"></div><div class="chart" id="b4"></div></div>
      </div>
      <div class="section-gap" id="b-table"></div>`;

    const ctl = sec.querySelector("#b-controls");
    control(ctl, "Model", seg("Model", [{ value: "both", label: "Both" }, { value: "mobilevit_s", label: "MobileViT-S" }, { value: "mobilevit_xxs", label: "MobileViT-XXS" }], state.model, (v) => {
      state.model = v; setParams("baseline", v === "both" ? {} : { model: v }); draw();
    }));

    function draw() {
      const models = state.model === "both" ? ["mobilevit_s", "mobilevit_xxs"] : [state.model];
      const conds = B.conditions.filter((c) => models.includes(c.model));
      const legend = models.map((m) => `<span class="k"><span class="sw dot" style="background:${MODEL_COLOR[m]}"></span>${MODEL[m]}</span>`).join("");
      ["#b1-legend", "#b2-legend", "#b4-legend"].forEach((id) => { sec.querySelector(id).innerHTML = models.length > 1 ? legend : ""; });
      const condTip = (c, extra) => tipRows(`${MODEL[c.model]} · ${fmt(c.input_fps, 0)} FPS · depth ${c.qos_depth}${c.delay_ms ? ` · +${c.delay_ms} ms` : ""}`, [
        ["offered FPS", fmt(c.offered_fps.mean, 2)], ["processed FPS", `${fmt(c.processed_fps.mean, 2)} ± ${fmt(c.processed_fps.sd, 2)}`],
        ["ρ", fmt(c.utilization.mean, 2)], ["drop", fmt(c.drop_rate_pct.mean, 1) + "%"], ["effective miss", fmt(c.effective_miss_rate_pct.mean, 1) + "%"],
        ["P50 / P99", `${fmt(c.p50_latency_ms.mean, 0)} / ${fmt(c.p99_latency_ms.mean, 0)} ms`], ["runs", c.n_runs], ...(extra || [])]);

      C.lineChart(sec.querySelector("#b1"), {
        series: models.map((m) => ({ name: MODEL[m].replace("MobileViT-", ""), color: MODEL_COLOR[m],
          points: conds.filter((c) => c.family === "fps" && c.model === m).map((c) => ({ x: c.offered_fps.mean, y: c.processed_fps.mean, tip: condTip(c) })) })),
        diag: "processed = offered", xTitle: "Offered FPS", yTitle: "Processed FPS", endLabels: true, ariaLabel: "Processed versus offered frames per second",
      });
      const runs = B.runs.filter((r) => models.includes(r.model));
      C.lineChart(sec.querySelector("#b2"), {
        scatter: true,
        series: models.map((m) => ({ name: MODEL[m], color: MODEL_COLOR[m],
          points: runs.filter((r) => r.model === m && r.expected_overload_drop_pct !== null).map((r) => ({ x: r.expected_overload_drop_pct, y: r.drop_rate_pct,
            tip: tipRows(r.run_id.replace(/_normal|_mobilevit/g, ""), [["predicted 1 − 1/ρ", fmt(r.expected_overload_drop_pct, 1) + "%"], ["measured drop", fmt(r.drop_rate_pct, 1) + "%"], ["ρ", fmt(r.utilization, 2)], ["depth", r.qos_depth], ["delay", r.delay_ms + " ms"]]) })) })),
        diag: "measured = predicted", xTitle: "Predicted drop 100·(1 − 1/ρ) (%)", yTitle: "Measured drop (%)", ariaLabel: "Measured versus predicted drop rate per run",
      });
      const q = conds.filter((c) => c.family === "qos").sort((a, b) => (a.model > b.model ? 1 : -1) || a.qos_depth - b.qos_depth);
      C.hbars(sec.querySelector("#b3"), {
        rows: q.map((c) => ({ group: models.length > 1 ? MODEL[c.model] : undefined, label: `depth ${c.qos_depth}`,
          segments: [{ v: c.p50_latency_ms.mean, color: MODEL_COLOR[c.model] }], marker: c.p99_latency_ms.mean,
          valueText: `${fmt(c.p50_latency_ms.mean, 0)} ms`, tip: condTip(c) })),
        refs: [{ value: 100, label: "deadline 100 ms" }], xTitle: "Latency (ms)", ariaLabel: "P50 latency by queue depth",
      });
      C.lineChart(sec.querySelector("#b4"), {
        series: models.map((m) => ({ name: MODEL[m].replace("MobileViT-", ""), color: MODEL_COLOR[m],
          points: conds.filter((c) => c.family === "overload" && c.model === m).map((c) => ({ x: c.delay_ms, y: c.effective_miss_rate_pct.mean, tip: condTip(c, [["delay", c.delay_ms + " ms"]]) })) })),
        xTitle: "Artificial delay per frame (ms)", yTitle: "Effective miss (%)", endLabels: true, yMax: 100, ariaLabel: "Effective miss versus artificial delay",
      });
      sec.querySelector("#b-table").innerHTML = table(
        [{ label: "Family", l: true }, { label: "Model", l: true }, { label: "FPS" }, { label: "Depth" }, { label: "Delay ms" }, { label: "n" }, { label: "Processed FPS" }, { label: "ρ" }, { label: "Drop %" }, { label: "1−1/ρ %" }, { label: "Deadline miss %" }, { label: "Eff. miss %" }, { label: "P50 ms" }, { label: "P99 ms" }, { label: "Inference ms" }, { label: "Detector CPU %" }, { label: "Max RSS MB" }, { label: "cgroup peak MB" }, { label: "Drop cause", l: true }],
        conds.map((c) => ({ cells: [c.family, MODEL[c.model], fmt(c.input_fps, 0), c.qos_depth, c.delay_ms, c.n_runs,
          `${fmt(c.processed_fps.mean, 2)} ± ${fmt(c.processed_fps.sd, 2)}`, fmt(c.utilization.mean, 2), fmt(c.drop_rate_pct.mean, 2), fmt(c.expected_overload_drop_pct.mean, 2),
          fmt(c.deadline_miss_rate_pct.mean, 1), fmt(c.effective_miss_rate_pct.mean, 1), fmt(c.p50_latency_ms.mean, 1), fmt(c.p99_latency_ms.mean, 1),
          fmt(c.avg_inference_ms.mean, 1), fmt(c.detector_cpu_pct.mean, 0), fmt(c.max_memory_mb.mean, 0), fmt(c.cgroup_memory_peak_mb.mean, 0), esc(c.drop_cause)] })),
        { toggle: `All ${conds.length} baseline conditions (mean ± SD across runs)` });
    }
    draw();
  }

  /* =============================== SCHEDULING =============================== */
  function renderScheduling(sec) {
    sec.innerHTML = `
      <div class="view-head"><h2>Six frame-scheduling policies, compared within blocks</h2>
      <p>Each block runs all six arms once, in rotated order, under identical controls. The run is the statistical unit and every comparison is a within-block paired difference. Deadline-Guard and Adaptive are always shown side by side.</p></div>
      <div class="controls" id="s-controls"></div>
      <p class="context" id="s-context"></p>
      <div class="grid">
        <div class="span-7 panel"><div class="fig-head"><div class="titles"><h3 id="s1-title"></h3><p class="fig-sub" id="s1-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>one run</span><span class="k"><span class="sw tick"></span>mean</span><span class="k"><span class="sw line" style="background:var(--axis)"></span>min–max</span></div>
          <div class="chart" id="s1"></div>
          <p class="fig-note">Latest-Frame, Deadline-Guard and Adaptive share the same queue, worker and controls, so this axis fits their range. FIFO and the legacy arms are on the full-scale chart below.</p></div>
        <div class="span-5 panel"><div class="fig-head"><div class="titles"><h3>Block by block</h3><p class="fig-sub" id="s2-sub"></p></div></div><div class="chart" id="s2"></div>
          <p class="fig-note">Each grey line is one experimental block. Running the arms back to back within a block reduces host-state variation between them; it does not make the host state identical.</p></div>
      </div>
      <div class="grid section-gap">
        <div class="span-7 panel"><div class="fig-head"><div class="titles"><h3>Paired differences: policy effect</h3><p class="fig-sub" id="s3-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>mean of block differences</span><span class="k"><span class="sw line" style="background:var(--ink)"></span>95% t-interval</span><span class="k"><span class="sw ring"></span>one block</span></div>
          <div class="chart" id="s3"></div>
          <p class="fig-note" id="s3-note"></p></div>
        <div class="span-5 panel"><div class="fig-head"><div class="titles"><h3>Against legacy depth 1</h3><p class="fig-sub">Includes the architecture difference (DDS callback vs queue + worker), so it is not attributable to a policy</p></div></div><div class="chart" id="s4"></div>
          <p class="fig-note">Legacy depth 1 varies strongly between runs (its service time is less stable), which is why these intervals are wide.</p></div>
      </div>
      <div class="panel section-gap"><div class="fig-head"><div class="titles"><h3 id="s5-title"></h3><p class="fig-sub" id="s5-sub"></p></div></div>
        <div class="chart" id="s5"></div>
        <p class="fig-note">The shaded range is where the three same-architecture arms fall. Legacy arms use a different execution path, so their gap to the application arms is not a policy effect.</p></div>
      <div class="section-gap" id="s-table"></div>
      <details class="table-toggle"><summary>Arm definitions</summary>${table([{ label: "Arm", l: true }, { label: "Path", l: true }, { label: "Behaviour", l: true, wrap: true }],
        D.arms.map((a) => ({ cells: [sw(ARM[a.id].color) + esc(a.label), a.family === "legacy" ? "Legacy (DDS callback)" : "Application queue + 1 worker", esc(a.summary)] })))}</details>`;

    const ctl = sec.querySelector("#s-controls");
    control(ctl, "Condition", seg("Condition", condOptions(), state.c, (v) => { state.c = v; sync(); draw(); }));
    control(ctl, "Metric", seg("Metric", Object.keys(METRICS).map((k) => ({ value: k, label: METRICS[k].label })), state.m, (v) => { state.m = v; sync(); draw(); }));
    function sync() { setParams("scheduling", { c: state.c, m: state.m }); }

    function armRows(cid, ids, M, c, group) {
      return ids.map((id) => {
        const r = armRow(cid, id), st = r[state.m];
        return { group: group ? group(id) : undefined, label: ARM[id].label, color: ARM[id].color, mean: st.mean, min: st.min, max: st.max, dim: ARM[id].family === "legacy",
          valueText: `${fmt(st.mean, M.nd)}${M.unit === "%" ? "%" : ""}`,
          points: runsOf(cid, id).map((x) => ({ v: x[state.m], label: `${ARM[id].label} block ${blockNo(x.block)}`,
            tip: tipRows(`${ARM[id].label} · block ${blockNo(x.block)}`, [["effective miss", fmt(x.effective_miss_rate_pct, 1) + "%"], ["on-time FPS", fmt(x.on_time_fps, 2)], ["P99", fmt(x.p99_latency_ms, 1) + " ms"], ["drop", fmt(x.drop_rate_pct, 1) + "%"], ["late (of processed)", fmt(x.deadline_miss_rate_pct, 1) + "%"], ["position in block", x.position]]) })),
          tip: tipRows(`${ARM[id].label} · ${c.label}`, [["mean ± SD", `${fmt(st.mean, M.nd)} ± ${fmt(st.sd, M.nd)}${M.unit}`], ["min – max", `${fmt(st.min, M.nd)} – ${fmt(st.max, M.nd)}`], ["drop", fmt(r.drop_rate_pct.mean, 1) + "%"], ["late (of processed)", fmt(r.deadline_miss_rate_pct.mean, 1) + "%"], ["service", fmt(r.avg_service_ms.mean, 1) + " ms"], ["runs", r.n_runs]]) };
      });
    }

    function draw() {
      const cid = state.c, c = COND[cid], M = METRICS[state.m];
      const latest = armRow(cid, "latest_q10");
      const overloaded = latest.utilization.mean >= 1;
      sec.querySelector("#s-context").innerHTML = `<b>${esc(c.label)}</b>${c.primary ? '<span class="pill">primary condition</span>' : ""} — ${c.n_blocks} blocks × 6 arms = ${c.n_runs} runs. Application arms run at ρ ≈ ${fmt(latest.utilization.mean, 2)} (${overloaded ? "overloaded" : "not overloaded"})${c.dynamic ? `, rate schedule <code>${esc(c.fps_schedule)}</code> (FPS@seconds)` : ""}; deadline ${fmt(c.deadline_ms, 0)} ms.`;

      const refs = state.m === "p99_latency_ms" ? [{ value: c.deadline_ms, label: "deadline" }] : [];
      const focus = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10"];
      sec.querySelector("#s1-title").textContent = `${M.label}: same-architecture arms`;
      sec.querySelector("#s1-sub").textContent = `${c.label} · ${c.n_blocks} runs per arm · ${M.better} is better`;
      C.dotRows(sec.querySelector("#s1"), { rows: armRows(cid, focus, M, c), xTitle: M.axis, nd: M.nd, refs, rowH: 40, ariaLabel: `${M.label}, Latest-Frame, Deadline-Guard and Adaptive` });

      const focusVals = [];
      focus.forEach((id) => runsOf(cid, id).forEach((x) => focusVals.push(x[state.m])));
      sec.querySelector("#s5-title").textContent = `All six arms on one scale`;
      sec.querySelector("#s5-sub").textContent = `${M.label} · ${c.label} · including FIFO and the legacy path`;
      const rows = armRows(cid, [...APP_ORDER, ...LEGACY_ORDER], M, c, (id) => ARM[id].family === "legacy" ? "Legacy path · different architecture" : "Application queue · same architecture");
      C.dotRows(sec.querySelector("#s5"), { rows, xTitle: M.axis, nd: M.nd, refs, rowH: 30,
        band: { lo: Math.min(...focusVals), hi: Math.max(...focusVals), label: refs.length ? undefined : "same-architecture range" }, ariaLabel: `${M.label} by arm, all arms` });

      const blocks = [...new Set(runsOf(cid, "latest_q10").map((r) => r.block))].sort();
      sec.querySelector("#s2-sub").textContent = `${M.label} · Latest → Guard → Adaptive · ${blocks.length} blocks`;
      C.slope(sec.querySelector("#s2"), {
        categories: focus.map((id) => ({ label: ARM[id].short, color: ARM[id].color })),
        lines: blocks.map((b) => {
          const vals = focus.map((id) => (runsOf(cid, id).find((r) => r.block === b) || {})[state.m]);
          return { name: `block ${blockNo(b)}`, values: vals,
            tip: tipRows(`Block ${blockNo(b)}`, focus.map((id, i) => [ARM[id].label, fmt(vals[i], M.nd) + M.unit])),
            pointTips: focus.map((id, i) => tipRows(`${ARM[id].label} · block ${blockNo(b)}`, [[M.label, fmt(vals[i], M.nd) + M.unit]])) };
        }),
        yTitle: M.label + (M.unit === "%" ? " (%)" : ` (${M.unit.trim()})`), zero: state.m !== "p99_latency_ms", ariaLabel: "Per-block slope chart",
      });

      const comps = [
        ["guard_c5_q10", "latest_q10"], ["adaptive_c5_q10", "latest_q10"], ["adaptive_c5_q10", "guard_c5_q10"],
        ["latest_q10", "legacy_q1"], ["guard_c5_q10", "legacy_q1"], ["adaptive_c5_q10", "legacy_q1"],
      ];
      const frows = comps.map(([a, ref]) => {
        const p = pairRow(cid, a, ref); const e = p.metrics[state.m];
        const same = p.comparison === "same_architecture";
        return { label: `${ARM[a].label} − ${ARM[ref].label}`, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM[a].color, dim: !same,
          sub: `${fmt(e.mean, M.dnd, true)}${M.d} ${ci(e, M.dnd)} · ${e.n_neg}↓ ${e.n_pos}↑ of ${p.n_blocks}`,
          points: same ? blockDiffs(cid, a, ref, state.m, e, p.n_blocks, M.dnd, M.d) : [],
          tip: tipRows(`${ARM[a].label} − ${ARM[ref].label}`, [["mean Δ", fmt(e.mean, M.dnd, true) + M.d], ["95% t-interval", ci(e, M.dnd)], ["SD of Δ", fmt(e.sd, M.dnd)], ["blocks lower / higher", `${e.n_neg} / ${e.n_pos}`], ["exact sign-flip p", fmt(e.signflip_p, 3)], ["blocks", p.n_blocks], ["comparison", same ? "same architecture" : "includes architecture difference"]]) };
      });
      sec.querySelector("#s3-sub").textContent = `Δ ${M.label} (${M.d.trim()}) · ${c.label} · ${c.n_blocks} blocks · ${M.better} is better`;
      C.forest(sec.querySelector("#s3"), { rows: frows.filter((r) => !r.dim), xTitle: `Δ ${M.label} (${M.d.trim()})`, ariaLabel: "Paired differences, same architecture" });
      C.forest(sec.querySelector("#s4"), { rows: frows.filter((r) => r.dim), xTitle: `Δ ${M.label} (${M.d.trim()})`, ariaLabel: "Paired differences versus legacy" });
      const floor = c.n_blocks >= 5 ? "0.0625" : c.n_blocks === 3 ? "0.25" : "—";
      const fe = pairRow(cid, "fifo_c5_q10", "latest_q10").metrics[state.m];
      sec.querySelector("#s3-note").innerHTML = `↓ / ↑ count blocks where the first arm was lower / higher. With n = ${c.n_blocks} blocks the smallest possible exact sign-flip p is ${floor}, so these counts are a consistency check, not a significance test. FIFO − Latest-Frame is off this scale: ${fmt(fe.mean, M.dnd, true)}${M.d} ${ci(fe, M.dnd)}.`;

      sec.querySelector("#s-table").innerHTML = table(
        [{ label: "Arm", l: true }, { label: "n" }, { label: "ρ" }, { label: "Processed FPS" }, { label: "On-time FPS" }, { label: "Drop %" }, { label: "Late % of processed" }, { label: "Eff. miss % (min–max)" }, { label: "Excl. tail %" }, { label: "P50 ms" }, { label: "P95 ms" }, { label: "P99 ms" }, { label: "P50 frame age ms" }, { label: "Service ms" }, { label: "CPU %" }, { label: "Max RSS MB" }],
        [...APP_ORDER, ...LEGACY_ORDER].map((id) => { const r = armRow(cid, id); return { hl: id === "guard_c5_q10" || id === "adaptive_c5_q10", cells: [
          sw(ARM[id].color) + esc(ARM[id].label), r.n_runs, fmt(r.utilization.mean, 2), fmt(r.processed_fps.mean, 1), `${fmt(r.on_time_fps.mean, 2)} ± ${fmt(r.on_time_fps.sd, 2)}`,
          fmt(r.drop_rate_pct.mean, 1), fmt(r.deadline_miss_rate_pct.mean, 1), `${fmt(r.effective_miss_rate_pct.mean, 1)} ± ${fmt(r.effective_miss_rate_pct.sd, 1)} (${fmt(r.effective_miss_rate_pct.min, 1)}–${fmt(r.effective_miss_rate_pct.max, 1)})`,
          fmt(r.effective_miss_excl_tail_pct.mean, 1), fmt(r.p50_latency_ms.mean, 1), fmt(r.p95_latency_ms.mean, 1), fmt(r.p99_latency_ms.mean, 1), fmt(r.p50_frame_age_at_start_ms.mean, 1),
          `${fmt(r.avg_service_ms.mean, 2)} ± ${fmt(r.avg_service_ms.sd, 2)}`, fmt(r.detector_cpu_pct.mean, 0), fmt(r.max_memory_mb.mean, 0)] }; }),
        { toggle: `Per-arm table · ${c.label} (mean ± SD across runs)` });
    }
    draw();
  }

  /* =============================== MECHANISM =============================== */
  // Concept illustration of the Deadline-Guard decision. The example ages and service estimate are
  // illustrative constants, not measurements; only the deadline comes from the data bundle.
  function conceptPanel(deadline) {
    const svc = 55, scale = 130;
    const ex = [
      { name: "Frame A", age: 30, verdict: "serve", note: "predicted to finish in time: run inference" },
      { name: "Frame B", age: 60, verdict: "drop", note: "predicted to miss: drop it and wait for the next frame" },
    ];
    const pct = (v) => `${(100 * v / scale).toFixed(2)}%`;
    const rows = ex.map((f) => { const tot = f.age + svc, ok = tot <= deadline;
      return `<div class="cg-row">
        <div class="cg-name"><b>${f.name}</b><span>age ${f.age} ms</span></div>
        <div class="cg-track" role="img" aria-label="${f.name}: age ${f.age} ms plus estimated service ${svc} ms equals ${tot} ms, ${ok ? "within" : "over"} the ${fmt(deadline, 0)} ms deadline">
          <span class="cg-age" style="width:${pct(f.age)}"></span><span class="cg-svc" style="width:${pct(svc)}"></span>
          <span class="cg-dl" style="left:${pct(deadline)}"></span>
        </div>
        <div class="cg-out"><span class="cg-sum">${tot} ms ${ok ? "≤" : ">"} ${fmt(deadline, 0)} ms</span><span class="cg-verdict ${ok ? "ok" : "no"}">${ok ? "Serve" : "Drop"}</span><span class="cg-note">${f.note}</span></div>
      </div>`; }).join("");
    return `<div class="panel concept"><div class="fig-head"><div class="titles"><h3>How Deadline-Guard decides</h3>
        <p class="fig-sub">When the worker is free, each queued frame's latency is predicted as <b>frame age</b> (now − publish time) + <b>estimated service time</b> (a quantile of recently measured service times). The guard serves the newest frame whose prediction fits the deadline.</p></div>
        <span class="tag">Concept illustration</span></div>
      <div class="legend"><span class="k"><span class="sw cg-sw-age"></span>frame age</span><span class="k"><span class="sw cg-sw-svc"></span>estimated service time</span><span class="k"><span class="sw dash"></span>deadline ${fmt(deadline, 0)} ms</span></div>
      ${rows}
      <p class="fig-note">Example values (age 30 / 60 ms, estimated service ${svc} ms) are illustrative, not measured. The measured inter-arrival and service times follow below.</p></div>`;
  }
  function renderMechanism(sec) {
    const Mx = D.mechanism, dyn = S.dynamic;
    const fixed = S.conditions.filter((c) => !c.dynamic);
    sec.innerHTML = `
      <div class="view-head"><h2>When and Why Deadline-Aware Scheduling Helps</h2>
      <p>Under overload, the newest frame waiting when the worker frees up is between 0 and one inter-arrival interval old. If that age plus the service time can exceed the deadline, Latest-Frame can spend inference time on frames that then finish late. Deadline-Guard predicts this before inference, drops frames predicted to miss, and waits for the next one.</p></div>
      ${conceptPanel(COND[D.primary_condition].deadline_ms)}
      <div class="panel section-gap"><div class="fig-head"><div class="titles"><h3>Worst-case age of the newest frame vs the deadline</h3><p class="fig-sub">inter-arrival interval (1000 / FPS) + measured Latest-Frame service time, per fixed-rate condition</p></div><span class="tag measured">Measured</span></div>
        <div class="legend"><span class="k"><span class="sw" style="background:var(--axis)"></span>inter-arrival (1000 / FPS)</span><span class="k"><span class="sw" style="background:var(--ink-2)"></span>service time (Latest-Frame, measured)</span><span class="k"><span class="sw dash"></span>deadline</span></div>
        <div class="chart" id="m1"></div><div id="m1-table" style="margin-top:14px"></div>
        <p class="fig-note">${esc(Mx.model_note)}</p></div>
      <div class="controls" id="m-controls" style="margin-top:var(--sp-7)"></div>
      <div class="grid">
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>What the effective miss is made of</h3><p class="fig-sub" id="m2-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw" style="background:var(--s7)"></span>dropped (never processed)</span><span class="k"><span class="sw" style="background:var(--s8)"></span>late (processed after the deadline)</span></div><div class="chart" id="m2"></div>
          <p class="fig-note">Guard trades a few more drops for almost no late frames. Shares are of all published frames.</p></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>Queueing: frame age when inference starts</h3><p class="fig-sub" id="m3-sub"></p></div></div><div class="chart" id="m3"></div>
          <p class="fig-note">Queues that serve the oldest frame (FIFO, legacy depth 5) make every frame wait for the whole backlog under overload.</p></div>
      </div>
      <div class="panel section-gap"><div class="fig-head"><div class="titles"><h3>Ablation: Adaptive − Deadline-Guard</h3><p class="fig-sub">Δ effective miss (pp), within-block, every condition and each phase of the dynamic run · Adaptive = Guard + utilisation switch</p></div></div>
        <div class="chart" id="m4"></div><div id="m4-table" style="margin-top:14px"></div>
        <p class="fig-note">The switch can only change a decision when ≥ 2 feasible frames are queued and estimated ρ &lt; 1. In these conditions the queue rarely holds two feasible frames, so EDF and newest-feasible pick the same frame.</p></div>
      ${dyn.condition ? `<div class="panel section-gap"><div class="fig-head"><div class="titles"><h3>Dynamic load: ${esc(COND[dyn.condition].label)}</h3><p class="fig-sub">Effective miss per phase (20 s each) · mean and min–max over ${COND[dyn.condition].n_blocks} runs per arm</p></div></div>
        <div class="grid" id="m5"></div><div id="m5-table" style="margin-top:6px"></div></div>` : ""}`;

    // M1 feasibility
    C.hbars(sec.querySelector("#m1"), {
      rows: Mx.feasibility.map((f) => ({ label: COND[f.condition].label, dim: !f.overloaded, segments: [
        { v: f.inter_arrival_ms, color: "var(--axis)", name: "inter-arrival" }, { v: f.service_ms, color: "var(--ink-2)", name: "service" }],
        valueText: `${fmt(f.age_bound_ms, 0)} ms`, valueNote: f.overloaded ? "" : "not overloaded, age ≈ 0",
        tip: tipRows(COND[f.condition].label, [["inter-arrival", fmt(f.inter_arrival_ms, 1) + " ms"], ["service (Latest)", fmt(f.service_ms, 1) + " ms"], ["sum", fmt(f.age_bound_ms, 1) + " ms"], ["ρ", fmt(f.utilization, 2)], ["overloaded", f.overloaded ? "yes" : "no"]]) })),
      refs: [{ value: Mx.feasibility[0].deadline_ms, label: `deadline ${fmt(Mx.feasibility[0].deadline_ms, 0)} ms` }], xTitle: "Milliseconds", rowH: 36, ariaLabel: "Inter-arrival plus service time versus deadline",
    });
    sec.querySelector("#m1-table").innerHTML = table(
      [{ label: "Condition", l: true }, { label: "ρ" }, { label: "Regime", l: true, wrap: true }, { label: "Predicted Latest late %" }, { label: "Observed Latest late %" }, { label: "Observed Guard late %" }, { label: "Guard − Latest Δ pp [95% CI] · blocks lower", wrap: true }],
      Mx.feasibility.map((f) => ({ hl: f.condition === D.primary_condition, cells: [esc(COND[f.condition].label), fmt(f.utilization, 2), esc(f.regime), fmt(f.predicted_latest_late_pct, 1), fmt(f.observed_latest_deadline_miss_pct, 1), fmt(f.observed_guard_deadline_miss_pct, 1),
        `${fmt(f.guard_minus_latest_eff_pp.mean, 2, true)} ${ci(f.guard_minus_latest_eff_pp, 2)} · ${f.guard_minus_latest_eff_pp.n_neg}/${COND[f.condition].n_blocks}`] })));

    const ctl = sec.querySelector("#m-controls");
    control(ctl, "Condition", seg("Condition", fixed.map((c) => ({ value: c.id, label: c.label, html: esc(c.label) + (c.primary ? '<span class="star">primary</span>' : "") })), state.mc, (v) => { state.mc = v; setParams("mechanism", { mc: v }); drawCond(); }));

    function drawCond() {
      const cid = state.mc, c = COND[cid];
      const order = [...APP_ORDER, ...LEGACY_ORDER];
      sec.querySelector("#m2-sub").textContent = `${c.label} · mean over ${c.n_blocks} runs per arm`;
      C.hbars(sec.querySelector("#m2"), {
        max: 100,
        rows: order.map((id) => { const r = armRow(cid, id);
          const drop = r.drop_rate_pct.mean, late = Math.max(0, r.late_share_pct);
          return { group: ARM[id].family === "legacy" ? "Legacy path" : "Application queue", label: ARM[id].label, dim: ARM[id].family === "legacy",
            segments: [{ v: drop, color: "var(--s7)", name: "dropped" }, { v: late, color: "var(--s8)", name: "late" }],
            valueText: fmt(r.effective_miss_rate_pct.mean, 1) + "%",
            tip: tipRows(`${ARM[id].label} · ${c.label}`, [["dropped", fmt(drop, 1) + "%"], ["late", fmt(late, 1) + "%"], ["effective miss", fmt(r.effective_miss_rate_pct.mean, 1) + "%"], ["policy drops", fmt(r.app_policy_drop_rate_pct.mean, 1) + "%"], ["DDS-unreceived / run", fmt(r.dds_unreceived_frames.mean, 0)]]) }; }),
        xTitle: "% of published frames", ariaLabel: "Dropped and late share by arm",
      });
      sec.querySelector("#m3-sub").textContent = `${c.label} · median age of a frame when its inference starts`;
      C.hbars(sec.querySelector("#m3"), {
        rows: order.map((id) => { const r = armRow(cid, id);
          return { group: ARM[id].family === "legacy" ? "Legacy path" : "Application queue", label: ARM[id].label, dim: ARM[id].family === "legacy",
            segments: [{ v: r.p50_frame_age_at_start_ms.mean, color: ARM[id].color }], valueText: `${fmt(r.p50_frame_age_at_start_ms.mean, 0)} ms`,
            tip: tipRows(`${ARM[id].label} · ${c.label}`, [["P50 frame age at start", fmt(r.p50_frame_age_at_start_ms.mean, 1) + " ms"], ["mean queue wait", r.avg_queue_wait_ms.mean === null ? "n/a (no app queue)" : fmt(r.avg_queue_wait_ms.mean, 1) + " ms"], ["max queue length", r.max_queue_len.mean === null ? "n/a" : fmt(r.max_queue_len.max, 0)], ["P50 latency", fmt(r.p50_latency_ms.mean, 1) + " ms"]]) }; }),
        refs: [{ value: c.deadline_ms, label: "deadline" }], xTitle: "Milliseconds", ariaLabel: "Frame age at inference start by arm",
      });
    }
    drawCond();

    // M4 ablation
    const abl = S.conditions.map((c) => ({ c, p: pairRow(c.id, "adaptive_c5_q10", "guard_c5_q10") }));
    const phaseName = (ph) => ["phase 1 · 10 FPS", "phase 2 · 20 FPS", "phase 3 · 10 FPS"][ph] || `phase ${ph + 1}`;
    const dynRows = (dyn.paired || []).filter((p) => p.arm === "adaptive_c5_q10" && p.reference === "guard_c5_q10" && p.phase > 0);
    const frows = abl.map(({ c, p }) => { const e = p.metrics.effective_miss_rate_pct;
      return { group: "Whole run", label: c.label, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM.adaptive_c5_q10.color,
        sub: `${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${e.n_neg}↓ ${e.n_pos}↑ of ${p.n_blocks}`,
        tip: tipRows(`Adaptive − Guard · ${c.label}`, [["mean Δ", fmt(e.mean, 2, true) + " pp"], ["95% CI", ci(e, 2)], ["blocks lower / higher", `${e.n_neg} / ${e.n_pos}`], ["sign-flip p", fmt(e.signflip_p, 3)]]) }; })
      .concat(dynRows.map((p) => { const e = p.metrics.effective_miss_pct;
        return { group: "Dynamic run · per phase", label: phaseName(p.phase), mean: e.mean, lo: e.lo, hi: e.hi, color: ARM.adaptive_c5_q10.color,
          sub: `${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${e.n_neg}↓ ${e.n_pos}↑ of ${p.n_blocks}`,
          tip: tipRows(`Adaptive − Guard · ${phaseName(p.phase)}`, [["mean Δ", fmt(e.mean, 2, true) + " pp"], ["95% CI", ci(e, 2)], ["blocks", p.n_blocks]]) }; }));
    C.forest(sec.querySelector("#m4"), { rows: frows, xTitle: "Δ effective miss (pp) · Adaptive − Deadline-Guard", ariaLabel: "Ablation forest plot" });
    const decKeys = (o) => Object.entries(o).map(([k, v]) => `${esc(k)} ${fmt(v, 0)}`).join(" · ") || "—";
    sec.querySelector("#m4-table").innerHTML = table(
      [{ label: "Condition", l: true }, { label: "Adaptive decisions / run", l: true }, { label: "Deadline-Guard decisions / run", l: true }, { label: "Adaptive drops / run", l: true }, { label: "Guard drops / run", l: true }],
      S.conditions.map((c) => { const a = Mx.decisions.find((d) => d.condition === c.id && d.arm === "adaptive_c5_q10"), gd = Mx.decisions.find((d) => d.condition === c.id && d.arm === "guard_c5_q10");
        return { cells: [esc(c.label), decKeys(a.decisions), decKeys(gd.decisions), decKeys(a.policy_drops), decKeys(gd.policy_drops)] }; }),
      { toggle: "Scheduler decision counts (mean per run, from the detector logs)" });

    // M5 dynamic
    if (dyn.condition) {
      const host = sec.querySelector("#m5");
      const phases = [...new Set(dyn.phases.map((p) => p.phase))].sort();
      phases.forEach((ph) => {
        const div = document.createElement("div"); div.className = "span-4";
        const tf = dyn.phases.find((p) => p.phase === ph).target_fps;
        div.innerHTML = `<h4>${esc(phaseName(ph).replace(/· \d+ FPS/, ""))}· ${fmt(tf, 0)} FPS</h4><div class="chart"></div>`;
        host.appendChild(div);
        C.dotRows(div.querySelector(".chart"), { valueW: 50, max: 100,
          rows: [...APP_ORDER, ...LEGACY_ORDER].map((id) => { const p = dyn.phases.find((x) => x.phase === ph && x.arm === id); const st = p.effective_miss_pct;
            return { label: ARM[id].short, color: ARM[id].color, mean: st.mean, min: st.min, max: st.max, dim: ARM[id].family === "legacy", valueText: fmt(st.mean, 1),
              tip: tipRows(`${ARM[id].label} · ${phaseName(ph)}`, [["effective miss", `${fmt(st.mean, 1)}% (${fmt(st.min, 1)}–${fmt(st.max, 1)})`], ["on-time FPS", fmt(p.on_time_fps.mean, 2)], ["P99", fmt(p.p99_latency_ms.mean, 1) + " ms"], ...(p.transient_effective_miss_pct.mean !== null ? [["first 3 s after step", fmt(p.transient_effective_miss_pct.mean, 1) + "%"]] : [])]) }; }),
          xTitle: "Effective miss (%)", ariaLabel: `Dynamic ${phaseName(ph)}` });
      });
      sec.querySelector("#m5-table").innerHTML = table(
        [{ label: "Arm", l: true }, ...phases.map((ph) => ({ label: `${phaseName(ph)} eff. %` })), { label: "Step-up first 3 s eff. %" }, { label: "Step-down first 3 s eff. %" }, { label: "Phase 2 P99 ms" }],
        [...APP_ORDER, ...LEGACY_ORDER].map((id) => { const ps = phases.map((ph) => dyn.phases.find((x) => x.phase === ph && x.arm === id));
          return { hl: id === "guard_c5_q10" || id === "adaptive_c5_q10", cells: [sw(ARM[id].color) + esc(ARM[id].label), ...ps.map((p) => fmt(p.effective_miss_pct.mean, 1)),
            fmt(ps[1] && ps[1].transient_effective_miss_pct.mean, 1), fmt(ps[2] && ps[2].transient_effective_miss_pct.mean, 1), fmt(ps[1] && ps[1].p99_latency_ms.mean, 1)] }; }),
        { toggle: "Per-phase table and step transients" });
    }
  }

  /* =============================== EVIDENCE =============================== */
  function renderEvidence(sec) {
    const B = D.baseline, K = D.kpis;
    const ok = '<svg class="ic ok" viewBox="0 0 18 18" aria-label="ok"><circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 9.2l2.3 2.3 4.7-4.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const allSame = (ctrls) => ctrls.every((x) => x.identical);
    const p3all = S.runs.length;
    const ctrlMap = {}; B.controls.forEach((x) => { ctrlMap[x.label] = { p2: x }; }); S.controls.forEach((x) => { (ctrlMap[x.label] = ctrlMap[x.label] || {}).p3 = x; });
    const showVal = (x) => !x ? "—" : x.values.map((v) => esc(Array.isArray(v) ? v.join(",") : typeof v === "number" && v >= 1 << 30 ? `${v} (${(v / (1 << 30)).toFixed(0)} GiB)` : /^[0-9a-f]{40,}$/.test(String(v)) ? String(v).slice(0, 12) + "…" : v)).join(" / ") + (x.identical ? "" : ` <span class="muted">(differs)</span>`);
    sec.innerHTML = `
      <div class="view-head"><h2>Where every number comes from</h2>
      <p>The dashboard bundle is generated by <code>python3 -m src.dashboard.build_data</code>. It refuses to write anything unless each table it reads matches its SHA-256 manifest down to the raw per-frame CSVs, every run is constrained and DDS-verified, and every block contains all six arms.</p></div>
      <div class="grid">
        <div class="span-6 panel"><h3>Checks passed when this bundle was built</h3>
          <ul class="status-list" style="margin-top:8px">
            <li>${ok}<div><div class="t">Phase 2 baseline chain</div><div class="x">${B.chain_records_verified} file records hash-verified (raw runs → runtime summary → baseline aggregates). ${B.n_runs} runs, all <code>constrained</code>, all DDS SHM-verified.</div></div></li>
            <li>${ok}<div><div class="t">Phase 3 formal A/B chain</div><div class="x">${S.chain_records_verified} file records hash-verified (raw runs → formal summary → per-arm, paired and dynamic-phase tables). ${p3all} runs in ${S.n_blocks} complete blocks.</div></div></li>
            <li>${ok}<div><div class="t">Measured code is the committed code</div><div class="x">Phase 3: ${S.commits.map((c) => `${c.runs} runs at <code>${c.commit}</code>, dirty=${c.dirty}`).join("; ")}. Phase 2: ${B.commits.map((c) => `${c.runs} at <code>${c.commit}</code>, dirty=${c.dirty}`).join("; ")}.</div></div></li>
            <li>${ok}<div><div class="t">Controls identical across runs</div><div class="x">${allSame(S.controls) ? "All" : "Not all"} ${S.controls.length} Phase 3 and ${allSame(B.controls) ? "all" : "not all"} ${B.controls.length} Phase 2 recorded controls hold a single value (table below).</div></div></li>
            <li>${ok}<div><div class="t">Excluded data cannot leak in</div><div class="x">Paths containing <code>pilot</code>, <code>legacy_unverified</code>, <code>example</code> or <code>runtime_aware</code>, and run ids outside the formal run tags, stop the build (tested).</div></div></li>
          </ul>
          <p class="fig-note">Independent gates (also in CI): <code>python3 scripts/check_runtime_provenance.py</code> (Phase 2) and <code>python3 scripts/check_phase3_provenance.py</code> (Phase 3) must both report VERIFIED.</p></div>
        <div class="span-6 panel"><h3>Run inventory</h3>
          ${table([{ label: "Dataset", l: true }, { label: "Runs" }, { label: "Design", l: true }],
            [{ cells: ["Phase 2 / Batch 2 baseline", B.n_runs, `${B.n_conditions} conditions × 3 runs · 60 s`] },
             ...S.conditions.map((c) => ({ hl: c.primary, cells: [`Phase 3 · ${esc(c.label)}${c.primary ? " (primary)" : ""}`, c.n_runs, `${c.n_blocks} blocks × 6 arms · 65 s`] })),
             { cells: ["<b>Total</b>", `<b>${K.runs.total}</b>`, ""] }])}
          <p class="fig-note">Phase 2 groups: ${Object.entries(B.run_groups).map(([k, v]) => `${esc(k)} ${v}`).join(", ")}. Warm-up: first 10 processed frames of every run excluded.</p></div>
      </div>
      <div class="panel section-gap"><h3>Controlled variables</h3><p class="fig-sub">Read from every run's <code>meta.json</code>; ✓ = one value across all runs of that phase.</p>
        <div style="margin-top:12px">${table([{ label: "Control", l: true }, { label: "Phase 2 baseline", l: true }, { label: "", l: false }, { label: "Phase 3 formal", l: true }, { label: "" }],
          Object.entries(ctrlMap).map(([k, v]) => ({ cells: [esc(k), showVal(v.p2), v.p2 ? (v.p2.identical ? '<span class="check">✓</span>' : "✗") : "", showVal(v.p3), v.p3 ? (v.p3.identical ? '<span class="check">✓</span>' : "✗") : ""] })))}</div>
        <p class="fig-note">Also fixed: COCO128 images cycled by the publisher, publisher RELIABLE depth 10 → detector BEST_EFFORT KEEP_LAST, application arms DDS depth 10 and queue capacity 5, host load gate before every Phase 3 block.</p></div>
      <div class="grid section-gap">
        <div class="span-6 panel"><h3>Statistical method</h3>
          <ul class="limits small" style="margin-top:8px">
            <li><b>Unit of analysis is the run.</b> Frames are never pooled into one large sample; ± is the SD across runs.</li>
            <li><b>Paired within blocks.</b> Every Phase 3 block runs all six arms once in rotated order; differences are taken inside a block, then averaged.</li>
            <li><b>95% Student-t interval</b> on the block differences, plus the number of blocks with a negative / positive difference and the exact two-sided sign-flip p.</li>
            <li><b>No significance claims.</b> With 5 blocks the smallest sign-flip p is 0.0625 (3 blocks: 0.25). Results are reported as effect size, interval and consistency.</li>
            <li><b>Causal comparisons only inside one architecture</b> (Guard / Adaptive / Latest / FIFO). Differences to the legacy path also contain an architecture effect.</li>
            <li><b>Pre-specified analysis plan.</b> The primary condition, metrics and comparisons were fixed in the project before the formal runs (an internal plan, not an external preregistration); Adaptive parameters were not tuned on the pilot.</li>
          </ul></div>
        <div class="span-6 panel"><h3>Known limitations</h3>
          <ul class="limits small" style="margin-top:8px">
            <li><b>One host, one session per phase.</b> i7-13700, two P-cores (12, 14), <code>powersave</code> governor, shared machine (load gate + nice 10). Results do not establish behaviour on other hardware.</li>
            <li><b>Small samples.</b> ${COND[D.primary_condition].n_blocks} blocks for the primary condition, ${Math.min(...S.conditions.map((c) => c.n_blocks))} for the others.</li>
            <li><b>“No difference” is not equivalence.</b> Adaptive − Guard intervals exclude effects larger than about 1–2 pp; no formal equivalence test was run.</li>
            <li><b>One parameter set.</b> 100 ms deadline, queue capacity 5, one Adaptive configuration, one step pattern for dynamic load. The utilisation switch might matter with ρ≈1 and longer queues, deadlines far above service time, or high service-time variance — untested.</li>
            <li><b>Architecture effects.</b> MobileViT-XXS application arms are ~1.2 ms slower per frame than legacy; legacy service time varies more between runs, cause not measured.</li>
            <li><b>Latency only.</b> Random-initialised weights; no accuracy. No energy was measured; EDA-Lite energy is a simulation estimate.</li>
          </ul></div>
      </div>
      <div class="grid section-gap">
        <div class="span-6 panel"><h3>Excluded from every KPI</h3>
          ${table([{ label: "Data", l: true, wrap: true }, { label: "Why", l: true, wrap: true }], D.excluded.map((e) => ({ cells: [`<code>${esc(e.path)}</code>`, esc(e.reason)] })))}</div>
        <div class="span-6 panel"><h3>Reproduce</h3>
          <pre class="cmd"># verify the measured data (exit 0 = VERIFIED)
python3 scripts/check_runtime_provenance.py
python3 scripts/check_phase3_provenance.py --expect-runs ${S.n_runs}

# rebuild this dashboard's data from the tables
python3 -m src.dashboard.build_data
python3 -m src.dashboard.build_data --check   # 0 = current

# preview on the server (localhost only; VS Code forwards it)
bash scripts/serve_dashboard.sh</pre>
          <p class="fig-note">Rebuilding the tables themselves from raw runs: see README → Reproducibility.</p></div>
      </div>
      <details class="table-toggle section-gap"><summary>All ${D.sources.length} source files with SHA-256</summary>
        ${table([{ label: "Path", l: true }, { label: "Role", l: true }, { label: "SHA-256", l: true }], D.sources.map((s) => ({ cells: [`<code>${esc(s.path)}</code>`, esc(s.role), `<code>${s.sha256.slice(0, 16)}…</code>`] })))}</details>`;
  }

  const RENDER = { overview: renderOverview, baseline: renderBaseline, scheduling: renderScheduling, mechanism: renderMechanism, evidence: renderEvidence };
  route();
})();
