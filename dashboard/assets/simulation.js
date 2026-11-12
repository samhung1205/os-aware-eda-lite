/* EDA-Lite simulation explorer. Data: window.DASHBOARD_DATA.simulation (estimates only). */
(function () {
  "use strict";
  const D = window.DASHBOARD_DATA;
  const C = window.Charts;
  const { fmt, esc } = C;
  const sec = document.getElementById("sim");
  sec.hidden = false;
  if (!D || !D.simulation || !D.simulation.rows || !D.simulation.rows.length) {
    sec.innerHTML = `<div class="empty-state"><h2>Simulation data not found</h2><p>Run <code>python3 -m src.dashboard.build_data</code>.</p></div>`;
    return;
  }
  const rows = D.simulation.rows;
  const MODEL = { mobilevit_s: "MobileViT-S (simplified)", mobilevit_xxs: "MobileViT-XXS (simplified)" };
  const SCHED = { layerwise: { label: "layerwise (no fusion)", color: "var(--s1)" }, greedy: { label: "greedy", color: "var(--s2)" }, dp: { label: "dp (exact)", color: "var(--s3)" } };
  const METRIC = {
    dram_traffic_kb: { label: "DRAM traffic", unit: "KB", nd: 0 },
    estimated_energy: { label: "Estimated energy", unit: "cost units", nd: 1 },
    estimated_latency_ms: { label: "Estimated latency", unit: "simulated ms", nd: 2 },
    os_aware_total_cost: { label: "OS-aware total cost", unit: "cost units", nd: 1 },
    num_subgraphs: { label: "Subgraphs", unit: "count", nd: 0 },
  };
  const profiles = [...new Set(rows.map((r) => r.os_profile))].sort((a, b) => (a === "pure" ? -1 : b === "pure" ? 1 : a < b ? -1 : 1));
  const params = new URLSearchParams(location.hash.slice(1));
  const st = { model: params.get("model") || "mobilevit_s", os: params.get("os") || "pure", m: params.get("m") || "dram_traffic_kb" };
  if (!MODEL[st.model]) st.model = "mobilevit_s";
  if (!profiles.includes(st.os)) st.os = profiles[0];
  if (!METRIC[st.m]) st.m = "dram_traffic_kb";

  // partitions identical across OS profiles? (computed, not asserted)
  const partKey = (r) => `${r.model}|${r.sram_kb}|${r.scheduler}`;
  const parts = {};
  rows.forEach((r) => { (parts[partKey(r)] = parts[partKey(r)] || new Set()).add(r.subgraphs); });
  const samePartition = Object.values(parts).every((s) => s.size === 1);

  sec.innerHTML = `
    <div class="view-head"><h2>Layer fusion under an SRAM budget</h2>
    <p>EDA-Lite splits a simplified MobileViT block profile into fused subgraphs that fit a given on-chip SRAM, then estimates DRAM traffic, energy and latency with a lightweight cost model. It is inspired by the EDA compiler paper; it does not reproduce it.</p></div>
    <div class="callout est"><p><b>Estimates, not measurements.</b> ${esc(D.simulation.note)} The verified ROS 2 results on the <a href="index.html#overview">measured dashboard</a> do not depend on anything on this page.</p></div>
    <div class="controls" id="c" style="margin-top:28px"></div>
    <div class="stat-row" id="stats"></div>
    <div class="grid section-gap">
      <div class="span-8 panel"><div class="fig-head"><div class="titles"><h3 id="t1"></h3><p class="fig-sub" id="s1"></p></div><span class="tag estimate">Estimate</span></div>
        <div class="legend" id="lg"></div><div class="chart" id="ch"></div><p class="fig-note" id="n1"></p></div>
      <div class="span-4 panel"><h3>How to read this</h3>
        <ul class="limits small" style="margin-top:8px">
          <li><b>layerwise</b> runs every block alone (the no-fusion baseline).</li>
          <li><b>greedy</b> fuses left to right while the subgraph fits SRAM.</li>
          <li><b>dp</b> finds the partition with the exact minimum OS-aware total cost (verified against an exhaustive oracle in the tests).</li>
          <li><b>OS profiles</b> (<code>pure</code>, <code>normal</code>, <code>high_latency</code>, <code>high_memory_pressure</code>) only re-weight the cost. ${samePartition ? "In this sweep they never change the chosen partition." : "In this sweep they change the chosen partition in some cases."}</li>
          <li>Profiles are coarse block summaries, not ONNX-exact graphs; energy and latency are in cost-model units.</li>
        </ul></div>
    </div>
    <div class="section-gap" id="tbl"></div>`;

  function seg(name, options, cur, pick) {
    const w = document.createElement("div"); w.className = "seg"; w.setAttribute("role", "group"); w.setAttribute("aria-label", name);
    options.forEach((o) => { const b = document.createElement("button"); b.type = "button"; b.textContent = o.label; b.setAttribute("aria-pressed", String(o.value === cur));
      b.onclick = () => { w.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false")); b.setAttribute("aria-pressed", "true"); pick(o.value); }; w.appendChild(b); });
    const box = document.createElement("div"); box.className = "control";
    box.innerHTML = `<span class="control-label">${esc(name)}</span>`; box.appendChild(w); return box;
  }
  const c = sec.querySelector("#c");
  const upd = () => { history.replaceState(null, "", `#model=${st.model}&os=${st.os}&m=${st.m}`); draw(); };
  c.appendChild(seg("Model", Object.keys(MODEL).map((k) => ({ value: k, label: k === "mobilevit_s" ? "MobileViT-S" : "MobileViT-XXS" })), st.model, (v) => { st.model = v; upd(); }));
  c.appendChild(seg("OS profile", profiles.map((p) => ({ value: p, label: p })), st.os, (v) => { st.os = v; upd(); }));
  c.appendChild(seg("Metric", Object.keys(METRIC).map((k) => ({ value: k, label: METRIC[k].label })), st.m, (v) => { st.m = v; upd(); }));

  function draw() {
    const M = METRIC[st.m];
    const sel = rows.filter((r) => r.model === st.model && r.os_profile === st.os);
    const srams = [...new Set(sel.map((r) => r.sram_kb))].sort((a, b) => a - b);
    const get = (s, k) => sel.find((r) => r.sram_kb === k && r.scheduler === s);
    const maxS = srams[srams.length - 1];
    const lw = get("layerwise", maxS), dp = get("dp", maxS);
    const red = (a, b) => (a && b && a !== 0 ? (100 * (a - b)) / a : null);
    sec.querySelector("#stats").innerHTML = [
      ["DRAM traffic, dp vs layerwise", red(lw && lw.dram_traffic_kb, dp && dp.dram_traffic_kb)],
      ["Energy estimate, dp vs layerwise", red(lw && lw.estimated_energy, dp && dp.estimated_energy)],
      ["Latency estimate, dp vs layerwise", red(lw && lw.estimated_latency_ms, dp && dp.estimated_latency_ms)],
    ].map(([l, v]) => `<div class="stat"><div class="label">${esc(l)} · ${maxS} KB SRAM</div><div class="v">${v === null ? "–" : fmt(-v, 1)}<span class="unit">%</span></div><div class="d">simulation estimate · ${esc(st.os)} profile</div></div>`).join("")
      + `<div class="stat"><div class="label">Subgraphs at ${maxS} KB</div><div class="v">${dp ? dp.num_subgraphs : "–"}<span class="unit">vs ${lw ? lw.num_subgraphs : "–"} layers</span></div><div class="d">max fusion depth ${dp ? dp.max_fusion_depth : "–"}</div></div>`;

    sec.querySelector("#t1").textContent = `${M.label} by SRAM budget`;
    sec.querySelector("#s1").textContent = `${MODEL[st.model]} · OS profile “${st.os}” · ${M.unit} · lower is better`;
    const ties = srams.every((k) => { const g = get("greedy", k), d = get("dp", k); return g && d && g.subgraphs === d.subgraphs; });
    sec.querySelector("#lg").innerHTML = Object.keys(SCHED).map((k) => `<span class="k"><span class="sw line" style="background:${SCHED[k].color}"></span>${esc(SCHED[k].label)}</span>`).join("");
    const lx = (k) => Math.log2(k);
    C.lineChart(sec.querySelector("#ch"), {
      series: Object.keys(SCHED).map((s) => ({ name: s === "dp" && ties ? "greedy = dp" : s === "greedy" && ties ? "" : SCHED[s].label, color: SCHED[s].color,
        points: srams.map((k) => get(s, k)).filter((r) => r && r.feasible).map((r) => ({ x: lx(r.sram_kb), y: r[st.m],
          tip: `<b>${esc(s)} · ${r.sram_kb} KB</b><div class="row"><span>${esc(M.label)}</span><span>${fmt(r[st.m], M.nd)}</span></div><div class="row"><span>subgraphs</span><span>${r.num_subgraphs}</span></div><div class="row"><span>peak SRAM</span><span>${fmt(r.peak_sram_kb, 0)} KB</span></div>` })) })),
      xMin: lx(srams[0]) - 0.25, xMax: lx(maxS) + 0.25, xZero: false, xTicks: srams.map(lx), xTickFmt: (v) => String(Math.round(Math.pow(2, v))), yZero: st.m === "num_subgraphs",
      xTitle: "SRAM budget (KB, log scale)", yTitle: `${M.label} (${M.unit})`, endLabels: true, ariaLabel: `${M.label} versus SRAM`,
    });
    sec.querySelector("#n1").textContent = ties ? "greedy and dp choose the same partition at every SRAM budget here, so their lines coincide; ties are reported as greedy = dp, never as a greedy win." : "";
    sec.querySelector("#tbl").innerHTML = `<details class="table-toggle"><summary>Schedules · ${esc(MODEL[st.model])} · ${esc(st.os)}</summary><div class="table-wrap"><table><thead><tr>
      <th class="l">SRAM KB</th><th class="l">Scheduler</th><th>Subgraphs</th><th>Max depth</th><th>Peak SRAM KB</th><th>DRAM KB</th><th>Energy (est.)</th><th>Latency (est.)</th><th>OS-aware cost</th><th class="l wrap">Partition</th></tr></thead><tbody>
      ${sel.map((r) => `<tr><td class="l">${r.sram_kb}</td><td class="l">${esc(r.scheduler)}</td><td>${r.num_subgraphs ?? "–"}</td><td>${r.max_fusion_depth ?? "–"}</td><td>${fmt(r.peak_sram_kb, 0)}</td><td>${fmt(r.dram_traffic_kb, 0)}</td><td>${fmt(r.estimated_energy, 1)}</td><td>${fmt(r.estimated_latency_ms, 2)}</td><td>${fmt(r.os_aware_total_cost, 1)}</td><td class="l wrap small">${esc(r.subgraphs)}</td></tr>`).join("")}
      </tbody></table></div></details>`;
  }
  draw();
})();
