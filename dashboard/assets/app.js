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
    document.title = { overview: "ROS 2 Scheduling Benchmark", baseline: "Baseline · ROS 2 Benchmark", scheduling: "Scheduling · ROS 2 Benchmark", mechanism: "Mechanism · ROS 2 Benchmark", evidence: "Evidence · ROS 2 Benchmark" }[view];
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
    span.innerHTML = `<span class="control-label">${esc(label)}</span>`;
    span.style.display = "flex"; span.style.alignItems = "center"; span.style.flexWrap = "wrap"; span.style.gap = "6px";
    span.appendChild(segEl); container.appendChild(span);
  }
  function table(headers, rows, opts) {
    opts = opts || {};
    const th = headers.map((h) => `<th class="${h.l ? "l" : ""} ${h.wrap ? "wrap" : ""}">${h.html || esc(h.label)}</th>`).join("");
    const tr = rows.map((r) => `<tr class="${r.hl ? "hl" : ""}">${r.cells.map((c, i) => `<td class="${headers[i] && headers[i].l ? "l" : ""} ${headers[i] && headers[i].wrap ? "wrap" : ""}">${c}</td>`).join("")}</tr>`).join("");
    const t = `<div class="table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
    return opts.toggle ? `<details class="table-toggle"${opts.open ? " open" : ""}><summary>${esc(opts.toggle)}</summary>${t}</details>` : t;
  }
  const condOptions = () => S.conditions.map((c) => ({ value: c.id, label: c.label, html: esc(c.label) + (c.primary ? '<span class="star" title="pre-registered primary condition">primary</span>' : "") }));

  /* =============================== OVERVIEW =============================== */
  function renderOverview(sec) {
    const K = D.kpis;
    const g = K.guard_vs_latest_primary, ag = K.adaptive_vs_guard_primary, al = K.adaptive_vs_latest_primary;
    const gd = K.guard_vs_latest_dynamic, agd = K.adaptive_vs_guard_dynamic;
    const pc = COND[D.primary_condition];
    const cap = K.capacity;
    const F = {}; D.findings.forEach((f) => { F[f.id] = f; });
    sec.innerHTML = `
      <div class="hero">
        <div>
          <p class="eyebrow">Phase 4 · Results at a glance</p>
          <h2>Dropping frames that can no longer meet the deadline is what helps — the adaptive switch adds nothing measurable.</h2>
          <p class="lede">A MobileViT detector in ROS 2 Humble runs pinned to two CPU cores with a 4 GiB memory limit and a Fast DDS shared-memory transport verified at run time.
          ${K.runs.total} constrained runs — a ${K.runs.phase2}-run baseline and a ${K.runs.phase3}-run interleaved A/B benchmark in ${K.runs.phase3_blocks} blocks — compare six frame-scheduling policies against a ${fmt(pc.deadline_ms, 0)} ms end-to-end deadline.</p>
        </div>
        <div class="hero-figure">
          <p class="eyebrow">Deadline-Guard − Latest-Frame · ${esc(pc.label)}</p>
          <div class="value">${fmt(g.mean, 1)}<span class="unit">pp</span></div>
          <div class="what">Effective miss (dropped + late frames), mean of ${g.n_blocks} within-block differences; lower in ${g.n_neg}/${g.n_blocks} blocks. Line: 95% t-interval ${ci(g, 2)}.</div>
          <div class="ci" id="hero-ci"></div>
        </div>
      </div>
      <div class="stat-row" style="margin-top:0">
        <div class="stat"><div class="label">Adaptive − Deadline-Guard · ${esc(pc.label)}</div><div class="v">${fmt(ag.mean, 2, true)}<span class="unit">pp</span></div><div class="d">95% CI ${ci(ag, 2)} · ${ag.n_neg} lower / ${ag.n_pos} higher</div></div>
        <div class="stat"><div class="label">Adaptive − Latest-Frame · ${esc(pc.label)}</div><div class="v">${fmt(al.mean, 1)}<span class="unit">pp</span></div><div class="d">95% CI ${ci(al, 2)} · ${al.n_neg}/${al.n_blocks} blocks lower</div></div>
        ${gd ? `<div class="stat"><div class="label">Guard − Latest · ${esc(COND[gd.condition].label)}</div><div class="v">${fmt(gd.mean, 1)}<span class="unit">pp</span></div><div class="d">95% CI ${ci(gd, 2)} · Adaptive − Guard ${fmt(agd.mean, 2, true)} pp</div></div>` : ""}
        <div class="stat"><div class="label">Saturated throughput</div><div class="v">${fmt(cap.mobilevit_s.mean, 1)}<span class="unit">FPS S</span> · ${fmt(cap.mobilevit_xxs.mean, 1)}<span class="unit">FPS XXS</span></div><div class="d">processed FPS of overloaded delay-0 runs (n=${cap.mobilevit_s.n_runs} / ${cap.mobilevit_xxs.n_runs})</div></div>
      </div>

      <div class="grid section-gap">
        <div class="span-6">
          <p class="eyebrow">Research questions</p>
          <ol class="qlist">
            <li><div class="q">Where does a MobileViT ROS 2 pipeline saturate on a constrained host, and why are frames lost?</div><div class="a">${esc(F.capacity.text)}</div></li>
            <li><div class="q">Which frame-scheduling policy keeps the most frames inside a ${fmt(pc.deadline_ms, 0)} ms deadline when the detector is overloaded?</div><div class="a">${esc(F.guard.text)}</div></li>
            <li><div class="q">Does Adaptive's utilisation switch add anything beyond a deadline feasibility check?</div><div class="a">${esc(F.adaptive.text)}</div></li>
          </ol>
        </div>
        <div class="span-6">
          <p class="eyebrow">Also established</p>
          <ul class="findings" style="grid-template-columns:1fr">
            ${["regime", "dynamic"].filter((k) => F[k]).map((k) => `<li><div class="t">${esc(F[k].title)}</div><div class="x">${esc(F[k].text)}</div></li>`).join("")}
            <li><div class="t">Comparisons with the legacy path are kept separate</div><div class="x">The legacy arms run inference inside the DDS callback; the application arms use an ingestion queue and one worker thread. Differences against legacy mix architecture and policy and are never attributed to a policy. <a href="#scheduling">See paired differences →</a></div></li>
          </ul>
        </div>
      </div>

      <div class="section-gap">
        <p class="eyebrow">System</p>
        <div class="panel">
          <div class="fig-head"><div class="titles"><h3>Two pipelines, one provenance rule</h3>
          <p class="fig-sub">Measured: ROS 2 publisher → Fast DDS SHM → detector with a scheduling policy → per-frame logs → hash-verified tables → this dashboard. Simulated: the offline EDA-Lite cost model, shown on its own page.</p></div></div>
          <img class="arch" src="assets/architecture.svg" alt="Architecture: image_stream_node publishes frames over Fast DDS shared memory to the MobileViT detector node. The legacy path runs inference in the DDS callback; the application path puts frames in a bounded queue served by one worker using FIFO, Latest-Frame, Deadline-Guard or Adaptive. Each run writes detector and publisher CSVs, metadata and a runtime probe; analysis tools build summaries and aggregates with SHA-256 manifests; provenance gates and the dashboard builder verify the chain. Separately, the EDA-Lite simulator turns simplified model profiles into cost-model estimates.">
        </div>
      </div>

      <div class="grid section-gap">
        <div class="span-6 panel">
          <div class="fig-head"><div class="titles"><h3>Verified runtime measurements</h3></div><span class="tag measured">Measured</span></div>
          <p class="small muted">Baseline, Scheduling, Mechanism and Evidence use only Phase 2 / Batch 2 baseline runs and Phase 3 / Batch 2 formal A/B runs. The bundle is built only if every table matches its SHA-256 manifest down to the raw CSVs. Pilot, legacy-unverified and example data are excluded.</p>
          <a href="#evidence" class="small">How the numbers are verified →</a>
        </div>
        <div class="span-6 panel">
          <div class="fig-head"><div class="titles"><h3>EDA-Lite simulation estimates</h3></div><span class="tag estimate">Estimates</span></div>
          <p class="small muted">Layer-fusion schedules for simplified MobileViT block profiles under SRAM limits: DRAM traffic, energy and latency in cost-model units. Not hardware measurements, and not linked to the runtime KPIs.</p>
          <a href="simulation.html" class="small">Open the simulation explorer →</a>
        </div>
      </div>`;
    C.ciStrip(sec.querySelector("#hero-ci"), g, { label: "95% confidence interval", color: ARM.guard_c5_q10.color,
      tip: tipRows("Deadline-Guard − Latest-Frame", [["mean", fmt(g.mean, 2) + " pp"], ["95% CI", ci(g, 2)], ["blocks lower", `${g.n_neg}/${g.n_blocks}`], ["sign-flip p", fmt(g.signflip_p, 3)]]) });
  }

  /* =============================== BASELINE =============================== */
  function renderBaseline(sec) {
    const B = D.baseline;
    const cap = B.capacity, dm = B.drop_model;
    sec.innerHTML = `
      <div class="view-head"><p class="eyebrow">Phase 2 · Baseline</p><h2>How MobileViT-S and -XXS behave before any scheduling</h2>
      <p>${B.n_runs} constrained runs over ${B.n_conditions} conditions (3 runs each): input rate, subscriber queue depth and injected service delay. Every run uses the legacy path (inference in the DDS callback).</p></div>
      <div class="controls" id="b-controls"></div>
      <div class="stat-row">
        <div class="stat"><div class="label">MobileViT-S saturated throughput</div><div class="v">${fmt(cap.mobilevit_s.mean, 1)}<span class="unit">FPS</span></div><div class="d">${fmt(cap.mobilevit_s.min, 1)}–${fmt(cap.mobilevit_s.max, 1)}, n=${cap.mobilevit_s.n_runs} runs · service ${fmt(cap.mobilevit_s.service_ms_mean, 1)} ms</div></div>
        <div class="stat"><div class="label">MobileViT-XXS saturated throughput</div><div class="v">${fmt(cap.mobilevit_xxs.mean, 1)}<span class="unit">FPS</span></div><div class="d">${fmt(cap.mobilevit_xxs.min, 1)}–${fmt(cap.mobilevit_xxs.max, 1)}, n=${cap.mobilevit_xxs.n_runs} runs · service ${fmt(cap.mobilevit_xxs.service_ms_mean, 1)} ms</div></div>
        <div class="stat"><div class="label">Worst drop rate below capacity (ρ &lt; 1)</div><div class="v">${fmt(dm.below_capacity_max_drop_pct, 2)}<span class="unit">%</span></div><div class="d">across ${dm.below_capacity_runs} runs: transport is effectively lossless</div></div>
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
      <div class="view-head"><p class="eyebrow">Phase 3 · Formal A/B</p><h2>Six frame-scheduling policies, interleaved in blocks</h2>
      <p>Each block runs all six arms once, in rotated order, under identical controls. The run is the statistical unit; comparisons are within-block paired differences. Deadline-Guard and Adaptive are always shown side by side.</p></div>
      <div class="controls" id="s-controls"></div>
      <div class="callout" id="s-context"></div>
      <div class="grid section-gap">
        <div class="span-7 panel"><div class="fig-head"><div class="titles"><h3 id="s1-title"></h3><p class="fig-sub" id="s1-sub"></p></div></div><div class="chart" id="s1"></div>
          <p class="fig-note">Dots: individual runs · vertical tick: mean · line: min–max across runs. Legacy arms use a different execution path, so their gap to the application arms is not a policy effect.</p></div>
        <div class="span-5 panel"><div class="fig-head"><div class="titles"><h3>Block by block</h3><p class="fig-sub" id="s2-sub"></p></div></div><div class="chart" id="s2"></div>
          <p class="fig-note">Each grey line is one block (the same host state for all three arms).</p></div>
      </div>
      <div class="grid section-gap">
        <div class="span-7 panel"><div class="fig-head"><div class="titles"><h3>Paired differences · policy effect</h3><p class="fig-sub" id="s3-sub"></p></div></div><div class="chart" id="s3"></div>
          <p class="fig-note" id="s3-note"></p></div>
        <div class="span-5 panel"><div class="fig-head"><div class="titles"><h3>vs Legacy depth 1</h3><p class="fig-sub">Includes the architecture difference (DDS callback vs queue + worker) — not attributable to a policy</p></div></div><div class="chart" id="s4"></div>
          <p class="fig-note">Legacy depth 1 varies strongly between runs (its service time is less stable), which is why these intervals are wide.</p></div>
      </div>
      <div class="section-gap" id="s-table"></div>
      <details class="table-toggle section-gap"><summary>Arm definitions</summary>${table([{ label: "Arm", l: true }, { label: "Path", l: true }, { label: "Behaviour", l: true, wrap: true }],
        D.arms.map((a) => ({ cells: [sw(ARM[a.id].color) + esc(a.label), a.family === "legacy" ? "Legacy (DDS callback)" : "Application queue + 1 worker", esc(a.summary)] })))}</details>`;

    const ctl = sec.querySelector("#s-controls");
    control(ctl, "Condition", seg("Condition", condOptions(), state.c, (v) => { state.c = v; sync(); draw(); }));
    control(ctl, "Metric", seg("Metric", Object.keys(METRICS).map((k) => ({ value: k, label: METRICS[k].label })), state.m, (v) => { state.m = v; sync(); draw(); }));
    function sync() { setParams("scheduling", { c: state.c, m: state.m }); }

    function draw() {
      const cid = state.c, c = COND[cid], M = METRICS[state.m];
      const latest = armRow(cid, "latest_q10");
      sec.querySelector("#s-context").innerHTML = `<p><b>${esc(c.label)}</b>${c.primary ? " · pre-registered primary condition" : ""} · ${c.n_blocks} blocks × 6 arms = ${c.n_runs} runs · ρ ≈ ${fmt(latest.utilization.mean, 2)} for the application arms (${latest.utilization.mean >= 1 ? "overloaded" : "not overloaded"})${c.dynamic ? ` · rate schedule <code>${esc(c.fps_schedule)}</code> (FPS@seconds)` : ""} · deadline ${fmt(c.deadline_ms, 0)} ms.</p>`;

      sec.querySelector("#s1-title").textContent = `${M.label} by arm`;
      sec.querySelector("#s1-sub").textContent = `${c.label} · n=${c.n_blocks} runs per arm · ${M.better} is better`;
      const rows = [];
      [["Application queue · same architecture", APP_ORDER], ["Legacy path · different architecture", LEGACY_ORDER]].forEach(([group, ids]) => {
        ids.forEach((id) => {
          const r = armRow(cid, id), st = r[state.m];
          rows.push({ group, label: ARM[id].label, color: ARM[id].color, mean: st.mean, min: st.min, max: st.max, dim: ARM[id].family === "legacy",
            valueText: `${fmt(st.mean, M.nd)}${M.unit === "%" ? "%" : ""}`,
            points: runsOf(cid, id).map((x) => ({ v: x[state.m], label: `${ARM[id].label} block ${blockNo(x.block)}`,
              tip: tipRows(`${ARM[id].label} · block ${blockNo(x.block)}`, [["effective miss", fmt(x.effective_miss_rate_pct, 1) + "%"], ["on-time FPS", fmt(x.on_time_fps, 2)], ["P99", fmt(x.p99_latency_ms, 1) + " ms"], ["drop", fmt(x.drop_rate_pct, 1) + "%"], ["late (of processed)", fmt(x.deadline_miss_rate_pct, 1) + "%"], ["position in block", x.position]]) })),
            tip: tipRows(`${ARM[id].label} · ${c.label}`, [["mean ± SD", `${fmt(st.mean, M.nd)} ± ${fmt(st.sd, M.nd)}${M.unit}`], ["min – max", `${fmt(st.min, M.nd)} – ${fmt(st.max, M.nd)}`], ["drop", fmt(r.drop_rate_pct.mean, 1) + "%"], ["late (of processed)", fmt(r.deadline_miss_rate_pct.mean, 1) + "%"], ["service", fmt(r.avg_service_ms.mean, 1) + " ms"], ["runs", r.n_runs]]) });
        });
      });
      C.dotRows(sec.querySelector("#s1"), { rows, xTitle: M.axis, nd: M.nd, refs: state.m === "p99_latency_ms" ? [{ value: c.deadline_ms, label: "deadline" }] : [], ariaLabel: `${M.label} by arm` });

      const cats = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10"];
      const blocks = [...new Set(runsOf(cid, "latest_q10").map((r) => r.block))].sort();
      sec.querySelector("#s2-sub").textContent = `${M.label} · Latest → Guard → Adaptive · ${blocks.length} blocks`;
      C.slope(sec.querySelector("#s2"), {
        categories: cats.map((id) => ({ label: ARM[id].short, color: ARM[id].color })),
        lines: blocks.map((b) => {
          const vals = cats.map((id) => (runsOf(cid, id).find((r) => r.block === b) || {})[state.m]);
          return { name: `block ${blockNo(b)}`, values: vals,
            tip: tipRows(`Block ${blockNo(b)}`, cats.map((id, i) => [ARM[id].label, fmt(vals[i], M.nd) + M.unit])),
            pointTips: cats.map((id, i) => tipRows(`${ARM[id].label} · block ${blockNo(b)}`, [[M.label, fmt(vals[i], M.nd) + M.unit]])) };
        }),
        yTitle: M.label + (M.unit === "%" ? " (%)" : ` (${M.unit.trim()})`), zero: state.m !== "p99_latency_ms", ariaLabel: "Per-block slope chart",
      });

      const comps = [
        ["Same architecture · policy effect", "guard_c5_q10", "latest_q10"], ["Same architecture · policy effect", "adaptive_c5_q10", "latest_q10"],
        ["Same architecture · policy effect", "adaptive_c5_q10", "guard_c5_q10"],
        ["vs Legacy depth 1 · includes architecture difference", "latest_q10", "legacy_q1"], ["vs Legacy depth 1 · includes architecture difference", "guard_c5_q10", "legacy_q1"],
        ["vs Legacy depth 1 · includes architecture difference", "adaptive_c5_q10", "legacy_q1"],
      ];
      const frows = comps.map(([group, a, ref]) => {
        const p = pairRow(cid, a, ref); const e = p.metrics[state.m];
        return { group, label: `${ARM[a].label} − ${ARM[ref].label}`, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM[a].color, dim: p.comparison !== "same_architecture",
          sub: `${fmt(e.mean, M.dnd, true)}${M.d} ${ci(e, M.dnd)} · ${e.n_neg}↓ ${e.n_pos}↑ of ${p.n_blocks}`,
          tip: tipRows(`${ARM[a].label} − ${ARM[ref].label}`, [["mean Δ", fmt(e.mean, M.dnd, true) + M.d], ["95% t-interval", ci(e, M.dnd)], ["SD of Δ", fmt(e.sd, M.dnd)], ["blocks lower / higher", `${e.n_neg} / ${e.n_pos}`], ["exact sign-flip p", fmt(e.signflip_p, 3)], ["blocks", p.n_blocks], ["comparison", p.comparison === "same_architecture" ? "same architecture" : "includes architecture difference"]]) };
      });
      sec.querySelector("#s3-sub").textContent = `Δ ${M.label} (${M.d.trim()}) · ${c.label} · same application architecture · mean and 95% Student-t interval over ${c.n_blocks} blocks · ${M.better} is better`;
      C.forest(sec.querySelector("#s3"), { rows: frows.filter((r) => !r.dim).map((r) => Object.assign({}, r, { group: undefined })), xTitle: `Δ ${M.label} (${M.d.trim()})`, ariaLabel: "Paired differences, same architecture" });
      C.forest(sec.querySelector("#s4"), { rows: frows.filter((r) => r.dim).map((r) => Object.assign({}, r, { group: undefined })), xTitle: `Δ ${M.label} (${M.d.trim()})`, ariaLabel: "Paired differences versus legacy" });
      const floor = c.n_blocks >= 5 ? "0.0625" : c.n_blocks === 3 ? "0.25" : "—";
      sec.querySelector("#s3-note").innerHTML = `With n = ${c.n_blocks} blocks the smallest possible exact sign-flip p is ${floor}, so block counts are reported as a consistency check, not as a significance test.
        FIFO − Latest-Frame is off this scale: ${(() => { const e = pairRow(cid, "fifo_c5_q10", "latest_q10").metrics[state.m]; return `${fmt(e.mean, M.dnd, true)}${M.d} ${ci(e, M.dnd)}`; })()}.`;

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
  function renderMechanism(sec) {
    const Mx = D.mechanism, dyn = S.dynamic;
    const fixed = S.conditions.filter((c) => !c.dynamic);
    sec.innerHTML = `
      <div class="view-head"><p class="eyebrow">Phase 3 · Mechanism &amp; ablation</p><h2>Why a deadline check helps in one regime and nowhere else</h2>
      <p>Under overload, the newest frame waiting when the worker frees up is between 0 and one inter-arrival interval old. If that age plus the service time can exceed the deadline, Latest-Frame processes frames that are already certain to be late. Deadline-Guard drops them and waits for the next one.</p></div>
      <div class="panel"><div class="fig-head"><div class="titles"><h3>Worst-case age of the newest frame vs the deadline</h3><p class="fig-sub">inter-arrival interval + measured Latest-Frame service time, per fixed-rate condition</p></div></div>
        <div class="legend"><span class="k"><span class="sw" style="background:var(--axis)"></span>inter-arrival (1000 / FPS)</span><span class="k"><span class="sw" style="background:var(--ink-2)"></span>service time (Latest-Frame, measured)</span><span class="k"><span class="sw dash"></span>deadline</span></div>
        <div class="chart" id="m1"></div><div id="m1-table" style="margin-top:14px"></div>
        <p class="fig-note">${esc(Mx.model_note)}</p></div>
      <div class="controls" id="m-controls" style="margin-top:44px"></div>
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
        valueText: f.overloaded ? `${fmt(f.age_bound_ms, 0)} ms` : `${fmt(f.age_bound_ms, 0)} ms · not overloaded, age ≈ 0`,
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
      <div class="view-head"><p class="eyebrow">Evidence</p><h2>Where every number comes from</h2>
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
            <li><b>Analysis plan fixed before the formal data</b>: primary condition, metrics and comparisons; Adaptive parameters were not tuned on the pilot.</li>
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
