/* Scheduling view: six arms compared within blocks. Numbers come from window.DASHBOARD_DATA through window.Dash (assets/app.js).
 * Text is written as L(english, traditional_chinese); see assets/i18n.js. */
(function () {
  "use strict";
  const X = window.Dash;
  if (!X) return;
  const { D, C, L, T, fmt, esc, S, ARM, COND, MODEL, MODEL_COLOR, APP_ORDER, LEGACY_ORDER, METRICS, betterText,
    armRow, pairRow, runsOf, blockNo, ci, tipRows, sw, blockDiffs, state, setParams, seg, control, table, spec, condOptions } = X;

  function renderScheduling(sec) {
    sec.innerHTML = `
      <div class="view-head"><h2>${L("Four policies and two legacy paths, compared within blocks", "四種 policy 與兩條 legacy 路徑，在 block 內比較")}</h2>
      <p>${L("Each block runs all six arms once, in rotated order, under identical controls. The run is the statistical unit and every comparison is a within-block paired difference. Deadline-Guard and Adaptive are always shown side by side.",
        "每個 block 在相同控制條件下，以輪替順序把六個 arms 各跑一次。統計單位是 run，所有比較都是 block 內的 paired difference。Deadline-Guard 與 Adaptive 一律並排呈現。")}</p></div>
      <div class="controls" id="s-controls"></div>
      <p class="context" id="s-context"></p>
      <div class="grid">
        <div class="span-7 fig"><div class="fig-head"><div class="titles"><h3 id="s1-title"></h3><p class="fig-sub" id="s1-sub"></p></div>${X.MEAS}</div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>${L("one run", "單一 run")}</span><span class="k"><span class="sw tick"></span>${L("mean", "平均")}</span><span class="k"><span class="sw line" style="background:var(--axis)"></span>min–max</span></div>
          <div class="chart" id="s1"></div>
          <p class="fig-note">${L("Latest-Frame, Deadline-Guard and Adaptive share the same queue, worker and controls, so this axis fits their range. FIFO and the legacy arms are on the full-scale chart below.",
            "Latest-Frame、Deadline-Guard 與 Adaptive 共用相同的 queue、worker 與控制條件，所以這張圖的座標軸只涵蓋它們的範圍。FIFO 與 legacy arms 請看下方完整刻度的圖。")}</p></div>
        <div class="span-5 fig"><div class="fig-head"><div class="titles"><h3>${L("Block by block", "逐 block 比較")}</h3><p class="fig-sub" id="s2-sub"></p></div>${X.MEAS}</div><div class="chart" id="s2"></div>
          <p class="fig-note">${L("Each grey line is one experimental block. Running the arms back to back within a block reduces host-state variation between them; it does not make the host state identical.",
            "每條灰線是一個實驗 block。在同一個 block 內連續執行各 arm，可以減少它們之間的主機狀態差異，但無法讓主機狀態完全相同。")}</p></div>
      </div>
      <div class="grid section-gap">
        <div class="span-7 fig" id="scheduling-paired"><div class="fig-head"><div class="titles"><h3>${L("Paired differences: policy effect", "Paired differences：policy 效果")}</h3><p class="fig-sub" id="s3-sub"></p></div>${X.MEAS}</div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>${L("mean of block differences", "block 差異的平均")}</span><span class="k"><span class="sw line" style="background:var(--ink)"></span>95% t-interval</span><span class="k"><span class="sw ring"></span>${L("one block", "單一 block")}</span></div>
          <div class="chart" id="s3"></div>
          <p class="fig-note" id="s3-note"></p></div>
        <div class="span-5 fig"><div class="fig-head"><div class="titles"><h3>${L("Against legacy depth 1", "與 legacy depth 1 比較")}</h3><p class="fig-sub">${L("Includes the architecture difference (DDS callback vs queue + worker), so it is not attributable to a policy", "包含 architecture 差異（DDS callback vs queue + worker），所以不能歸因於 policy")}</p></div>${X.MEAS}</div><div class="chart" id="s4"></div>
          <p class="fig-note">${L("Legacy depth 1 varies strongly between runs (its service time is less stable), which is why these intervals are wide.", "Legacy depth 1 在不同 run 之間變動很大（service time 較不穩定），所以這些區間很寬。")}</p></div>
      </div>
      <div class="fig section-gap"><div class="fig-head"><div class="titles"><h3 id="s5-title"></h3><p class="fig-sub" id="s5-sub"></p></div>${X.MEAS}</div>
        <div class="chart" id="s5"></div>
        <p class="fig-note">${L("The shaded range is where the three same-architecture arms fall. Legacy arms use a different execution path, so their gap to the application arms is not a policy effect.",
          "陰影範圍是三個相同 architecture arms 的分布範圍。Legacy arms 使用不同的執行路徑，所以它們與 application arms 的差距不是 policy 效果。")}</p></div>
      <div class="section-gap" id="s-table"></div>
      <details class="table-toggle"><summary>${L("Arm definitions", "Arm 定義")}</summary>${table([{ label: "Arm", l: true }, { label: L("Path", "路徑"), l: true }, { label: L("Behaviour", "行為"), l: true, wrap: true }],
        D.arms.map((a) => ({ cells: [sw(ARM[a.id].color) + esc(a.label), a.family === "legacy" ? L("Legacy (DDS callback)", "Legacy（DDS callback）") : L("Application queue + 1 worker", "Application queue + 1 個 worker"), esc(T(a, "summary"))] })))}</details>`;

    const ctl = sec.querySelector("#s-controls");
    control(ctl, L("Condition", "條件"), seg(L("Condition", "條件"), condOptions(), state.c, (v) => { state.c = v; sync(); draw(); }));
    control(ctl, L("Metric", "指標"), seg(L("Metric", "指標"), Object.keys(METRICS).map((k) => ({ value: k, label: METRICS[k].label })), state.m, (v) => { state.m = v; sync(); draw(); }));
    function sync() { setParams("scheduling", { c: state.c, m: state.m }); }

    function armRows(cid, ids, M, c, group) {
      return ids.map((id) => {
        const r = armRow(cid, id), st = r[state.m];
        return { group: group ? group(id) : undefined, label: ARM[id].label, color: ARM[id].color, mean: st.mean, min: st.min, max: st.max, dim: ARM[id].family === "legacy",
          valueText: `${fmt(st.mean, M.nd)}${M.unit === "%" ? "%" : ""}`,
          points: runsOf(cid, id).map((x) => ({ v: x[state.m], label: `${ARM[id].label} block ${blockNo(x.block)}`,
            tip: tipRows(`${ARM[id].label} · block ${blockNo(x.block)}`, [["effective miss", fmt(x.effective_miss_rate_pct, 1) + "%"], ["on-time FPS", fmt(x.on_time_fps, 2)], ["P99", fmt(x.p99_latency_ms, 1) + " ms"], ["drop", fmt(x.drop_rate_pct, 1) + "%"], [L("late (of processed)", "late（占 processed）"), fmt(x.deadline_miss_rate_pct, 1) + "%"], [L("position in block", "block 內順序"), x.position]]) })),
          tip: tipRows(`${ARM[id].label} · ${c.label}`, [["mean ± SD", `${fmt(st.mean, M.nd)} ± ${fmt(st.sd, M.nd)}${M.unit}`], ["min – max", `${fmt(st.min, M.nd)} – ${fmt(st.max, M.nd)}`], ["drop", fmt(r.drop_rate_pct.mean, 1) + "%"], [L("late (of processed)", "late（占 processed）"), fmt(r.deadline_miss_rate_pct.mean, 1) + "%"], ["service", fmt(r.avg_service_ms.mean, 1) + " ms"], ["runs", r.n_runs]]) };
      });
    }

    function draw() {
      const cid = state.c, c = COND[cid], M = METRICS[state.m];
      const latest = armRow(cid, "latest_q10");
      const overloaded = latest.utilization.mean >= 1;
      const rho = fmt(latest.utilization.mean, 2), dl = fmt(c.deadline_ms, 0);
      sec.querySelector("#s-context").innerHTML = `<b>${esc(c.label)}</b>${c.primary ? `<span class="ctx-tag">${L("primary condition", "主要 condition")}</span>` : ""} — ` + L(
        `${c.n_blocks} blocks × 6 arms = ${c.n_runs} runs. Application arms run at ρ ≈ ${rho} (${overloaded ? "overloaded" : "not overloaded"})${c.dynamic ? `, rate schedule <code>${esc(c.fps_schedule)}</code> (FPS@seconds)` : ""}; deadline ${dl} ms.`,
        `${c.n_blocks} blocks × 6 arms = ${c.n_runs} runs。Application arms 的 ρ ≈ ${rho}（${overloaded ? "過載" : "未過載"}）${c.dynamic ? `，速率排程 <code>${esc(c.fps_schedule)}</code>（FPS@秒）` : ""}；deadline ${dl} ms。`);

      const refs = state.m === "p99_latency_ms" ? [{ value: c.deadline_ms, label: "deadline" }] : [];
      const focus = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10"];
      sec.querySelector("#s1-title").textContent = L(`${M.label}: same-architecture arms`, `${M.label}：相同 architecture 的 arms`);
      sec.querySelector("#s1-sub").textContent = L(`${c.label} · ${c.n_blocks} runs per arm · ${betterText(M)}`, `${c.label} · 每個 arm ${c.n_blocks} runs · ${betterText(M)}`);
      C.dotRows(sec.querySelector("#s1"), { rows: armRows(cid, focus, M, c), xTitle: M.axis, nd: M.nd, refs, rowH: 40, ariaLabel: L(`${M.label}, Latest-Frame, Deadline-Guard and Adaptive`, `${M.label}：Latest-Frame、Deadline-Guard 與 Adaptive`) });

      const focusVals = [];
      focus.forEach((id) => runsOf(cid, id).forEach((x) => focusVals.push(x[state.m])));
      sec.querySelector("#s5-title").textContent = L(`All six arms on one scale`, `六個 arms 放在同一刻度`);
      sec.querySelector("#s5-sub").textContent = L(`${M.label} · ${c.label} · including FIFO and the legacy path`, `${M.label} · ${c.label} · 包含 FIFO 與 legacy 路徑`);
      const rows = armRows(cid, [...APP_ORDER, ...LEGACY_ORDER], M, c, (id) => ARM[id].family === "legacy" ? L("Legacy path · different architecture", "Legacy 路徑 · 不同 architecture") : L("Application queue · same architecture", "Application queue · 相同 architecture"));
      C.dotRows(sec.querySelector("#s5"), { rows, xTitle: M.axis, nd: M.nd, refs, rowH: 30,
        band: { lo: Math.min(...focusVals), hi: Math.max(...focusVals), label: refs.length ? undefined : L("same-architecture range", "相同 architecture 範圍") }, ariaLabel: L(`${M.label} by arm, all arms`, `各 arm 的 ${M.label}（全部 arms）`) });

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
        yTitle: M.label + (M.unit === "%" ? " (%)" : ` (${M.unit.trim()})`), ariaLabel: L("Per-block slope chart", "逐 block slope chart"),
      });

      const comps = [
        ["guard_c5_q10", "latest_q10"], ["adaptive_c5_q10", "latest_q10"], ["adaptive_c5_q10", "guard_c5_q10"],
        ["latest_q10", "legacy_q1"], ["guard_c5_q10", "legacy_q1"], ["adaptive_c5_q10", "legacy_q1"],
      ];
      const frows = comps.map(([a, ref]) => {
        const p = pairRow(cid, a, ref); const e = p.metrics[state.m];
        const same = p.comparison === "same_architecture";
        return { label: `${ARM[a].label} − ${ARM[ref].label}`, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM[a].color, dim: !same,
          sub: L(`${fmt(e.mean, M.dnd, true)}${M.d} ${ci(e, M.dnd)} · ${e.n_neg}↓ ${e.n_pos}↑ of ${p.n_blocks}`, `${fmt(e.mean, M.dnd, true)}${M.d} ${ci(e, M.dnd)} · ${p.n_blocks} 中 ${e.n_neg}↓ ${e.n_pos}↑`),
          points: same ? blockDiffs(cid, a, ref, state.m, e, p.n_blocks, M.dnd, M.d) : [],
          tip: tipRows(`${ARM[a].label} − ${ARM[ref].label}`, [["mean Δ", fmt(e.mean, M.dnd, true) + M.d], ["95% t-interval", ci(e, M.dnd)], ["SD of Δ", fmt(e.sd, M.dnd)], [L("blocks lower / higher", "blocks 較低 / 較高"), `${e.n_neg} / ${e.n_pos}`], ["exact sign-flip p", fmt(e.signflip_p, 3)], ["blocks", p.n_blocks], [L("comparison", "比較類型"), same ? L("same architecture", "相同 architecture") : L("includes architecture difference", "包含 architecture 差異")]]) };
      });
      sec.querySelector("#s3-sub").textContent = `Δ ${M.label} (${M.d.trim()}) · ${c.label} · ${c.n_blocks} blocks · ${betterText(M)}`;
      C.forest(sec.querySelector("#s3"), { rows: frows.filter((r) => !r.dim), xTitle: `Δ ${M.label} (${M.d.trim()})`, ariaLabel: L("Paired differences, same architecture", "Paired differences，相同 architecture") });
      C.forest(sec.querySelector("#s4"), { rows: frows.filter((r) => r.dim), xTitle: `Δ ${M.label} (${M.d.trim()})`, ariaLabel: L("Paired differences versus legacy", "與 legacy 的 paired differences") });
      const floor = c.n_blocks >= 5 ? "0.0625" : c.n_blocks === 3 ? "0.25" : "—";
      const fe = pairRow(cid, "fifo_c5_q10", "latest_q10").metrics[state.m];
      sec.querySelector("#s3-note").innerHTML = L(
        `↓ / ↑ count blocks where the first arm was lower / higher. With n = ${c.n_blocks} blocks the smallest possible exact sign-flip p is ${floor}, so these counts are a consistency check, not a significance test. FIFO − Latest-Frame is not drawn here: ${fmt(fe.mean, M.dnd, true)}${M.d} ${ci(fe, M.dnd)}.`,
        `↓ / ↑ 表示第一個 arm 較低 / 較高的 block 數。n = ${c.n_blocks} blocks 時，exact sign-flip p 最小只能到 ${floor}，所以這些計數只是一致性檢查，不是顯著性檢定。FIFO − Latest-Frame 未畫在此圖：${fmt(fe.mean, M.dnd, true)}${M.d} ${ci(fe, M.dnd)}。`);

      sec.querySelector("#s-table").innerHTML = table(
        [{ label: "Arm", l: true }, { label: "n" }, { label: "ρ" }, { label: "Processed FPS" }, { label: "On-time FPS" }, { label: "Drop %" }, { label: L("Late % of processed", "Late %（占 processed）") }, { label: "Eff. miss % (min–max)" }, { label: "Excl. tail %" }, { label: "P50 ms" }, { label: "P95 ms" }, { label: "P99 ms" }, { label: "P50 frame age ms" }, { label: "Service ms" }, { label: "CPU %" }, { label: "Max RSS MB" }],
        [...APP_ORDER, ...LEGACY_ORDER].map((id) => { const r = armRow(cid, id); return { hl: id === "guard_c5_q10" || id === "adaptive_c5_q10", cells: [
          sw(ARM[id].color) + esc(ARM[id].label), r.n_runs, fmt(r.utilization.mean, 2), fmt(r.processed_fps.mean, 1), `${fmt(r.on_time_fps.mean, 2)} ± ${fmt(r.on_time_fps.sd, 2)}`,
          fmt(r.drop_rate_pct.mean, 1), fmt(r.deadline_miss_rate_pct.mean, 1), `${fmt(r.effective_miss_rate_pct.mean, 1)} ± ${fmt(r.effective_miss_rate_pct.sd, 1)} (${fmt(r.effective_miss_rate_pct.min, 1)}–${fmt(r.effective_miss_rate_pct.max, 1)})`,
          fmt(r.effective_miss_excl_tail_pct.mean, 1), fmt(r.p50_latency_ms.mean, 1), fmt(r.p95_latency_ms.mean, 1), fmt(r.p99_latency_ms.mean, 1), fmt(r.p50_frame_age_at_start_ms.mean, 1),
          `${fmt(r.avg_service_ms.mean, 2)} ± ${fmt(r.avg_service_ms.sd, 2)}`, fmt(r.detector_cpu_pct.mean, 0), fmt(r.max_memory_mb.mean, 0)] }; }),
        { toggle: L(`Per-arm table · ${c.label} (mean ± SD across runs)`, `各 arm 數據表 · ${c.label}（各 runs 的 mean ± SD）`) });
    }
    draw();
  }

  X.views.scheduling = renderScheduling;
})();
