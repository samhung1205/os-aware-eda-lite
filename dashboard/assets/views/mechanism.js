/* Mechanism view: why and when the deadline check helps. Numbers come from window.DASHBOARD_DATA through window.Dash (assets/app.js).
 * Text is written as L(english, traditional_chinese); see assets/i18n.js. */
(function () {
  "use strict";
  const X = window.Dash;
  if (!X) return;
  const { D, C, L, T, fmt, esc, S, ARM, COND, MODEL, MODEL_COLOR, APP_ORDER, LEGACY_ORDER, METRICS, betterText,
    armRow, pairRow, runsOf, blockNo, ci, tipRows, sw, blockDiffs, state, setParams, seg, control, table, spec, condOptions } = X;

  // Concept illustration of the Deadline-Guard decision. The example ages and service estimate are
  // illustrative constants, not measurements; only the deadline comes from the data bundle.
  function conceptPanel(deadline) {
    const svc = 55, scale = 130;
    const ex = [
      { name: "Frame A", age: 30, verdict: "serve", note: L("predicted to finish in time: run inference", "預測能準時完成：執行 inference") },
      { name: "Frame B", age: 60, verdict: "drop", note: L("predicted to miss: drop it and wait for the next frame", "預測會錯過：丟棄並等待下一個 frame") },
    ];
    const pct = (v) => `${(100 * v / scale).toFixed(2)}%`;
    const dl = fmt(deadline, 0);
    const rows = ex.map((f) => { const tot = f.age + svc, ok = tot <= deadline;
      return `<div class="cg-row">
        <div class="cg-name"><b>${f.name}</b><span>age ${f.age} ms</span></div>
        <div class="cg-track" role="img" aria-label="${L(`${f.name}: age ${f.age} ms plus estimated service ${svc} ms equals ${tot} ms, ${ok ? "within" : "over"} the ${dl} ms deadline`, `${f.name}：age ${f.age} ms 加上估計 service ${svc} ms 等於 ${tot} ms，${ok ? "在" : "超過"} ${dl} ms deadline${ok ? "內" : ""}`)}">
          <span class="cg-rel"></span><span class="cg-age" style="width:${pct(f.age)}"></span><span class="cg-svc" style="width:${pct(Math.min(svc, Math.max(0, deadline - f.age)))}"></span>${ok ? "" : `<span class="cg-over" style="width:${pct(tot - Math.max(deadline, f.age))}"></span>`}
          <span class="cg-dl" style="left:${pct(deadline)}"></span>
        </div>
        <div class="cg-out"><span class="cg-sum">${tot} ms ${ok ? "≤" : ">"} ${dl} ms</span><span class="cg-verdict ${ok ? "ok" : "no"}">${ok ? L("Serve", "處理") : L("Drop", "丟棄")}</span><span class="cg-note">${f.note}</span></div>
      </div>`; }).join("");
    return `<div class="fig concept"><div class="fig-head"><div class="titles"><h3>${L("How Deadline-Guard decides", "Deadline-Guard 如何做決定")}</h3>
        <p class="fig-sub">${L("When the worker is free, each queued frame's latency is predicted as <b>frame age</b> (now − publish time) + <b>estimated service time</b> (a quantile of recently measured service times). The guard serves the newest frame whose prediction fits the deadline.",
          "Worker 空閒時，每個排隊中 frame 的 latency 預測為 <b>frame age</b>（現在 − publish 時間）+ <b>估計 service time</b>（最近實測 service time 的分位數）。Guard 會處理預測值落在 deadline 內的最新 frame。")}</p></div>
        <span class="tag">${L("Concept illustration", "概念示意")}</span></div>
      <div class="legend"><span class="k"><span class="sw open"></span>frame age</span><span class="k"><span class="sw hatch"></span>${L("estimated service time", "估計 service time")}</span><span class="k"><span class="sw overshoot-sw"></span>${L("predicted past the deadline", "預測超過 deadline")}</span><span class="k"><span class="sw dash"></span>deadline ${dl} ms</span></div>
      ${rows}
      <p class="fig-note">${L(`Example values (age 30 / 60 ms, estimated service ${svc} ms) are illustrative, not measured. The measured inter-arrival and service times follow below.`,
        `範例數值（age 30 / 60 ms，估計 service ${svc} ms）僅為示意，不是實測。實測的 inter-arrival 與 service time 見下方。`)}</p></div>`;
  }
  function renderMechanism(sec) {
    const Mx = D.mechanism, dyn = S.dynamic;
    const fixed = S.conditions.filter((c) => !c.dynamic);
    sec.innerHTML = `
      <div class="view-head"><h2>${L("When and Why Deadline-Aware Scheduling Helps", "Deadline-aware scheduling 何時有效、為什麼有效")}</h2>
      <p>${L("Under overload, the newest frame waiting when the worker frees up is between 0 and one inter-arrival interval old. If that age plus the service time can exceed the deadline, Latest-Frame can spend inference time on frames that then finish late. Deadline-Guard predicts this before inference, drops frames predicted to miss, and waits for the next one.",
        "過載時，worker 空出來那一刻，等待中最新的 frame 其 age 介於 0 到一個 inter-arrival 間隔之間。如果這個 age 加上 service time 可能超過 deadline，Latest-Frame 就可能把 inference 時間花在最後遲到的 frame 上。Deadline-Guard 會在 inference 前預測這種情況，丟棄預測會錯過的 frame，改等下一個。")}</p></div>
      ${conceptPanel(COND[D.primary_condition].deadline_ms)}
      <div class="fig section-gap"><div class="fig-head"><div class="titles"><h3>${L("Worst-case age of the newest frame vs the deadline", "最新 frame 的最壞情況 age vs deadline")}</h3><p class="fig-sub">${L("Waiting up to one inter-arrival interval (1000 / FPS, only when overloaded) + measured Latest-Frame service time, per fixed-rate condition", "各固定速率 condition：最多一個 inter-arrival 間隔的等待（1000 / FPS，僅過載時）+ 實測 Latest-Frame service time")}</p></div><span class="tag measured">${L("Measured", "實測")}</span></div>
        <div class="legend"><span class="k"><span class="sw open"></span>inter-arrival (1000 / FPS)</span><span class="k"><span class="sw solid"></span>${L("service time (Latest-Frame, measured)", "service time（Latest-Frame，實測）")}</span><span class="k"><span class="sw dash"></span>deadline</span></div>
        <div class="chart" id="m1"></div><div id="m1-table" style="margin-top:var(--sp-4)"></div>
        <p class="fig-note">${esc(T(Mx, "model_note"))}</p></div>
      <div class="controls" id="m-controls" style="margin-top:var(--sp-9)"></div>
      <div class="grid">
        <div class="span-6 fig"><div class="fig-head"><div class="titles"><h3>${L("What the effective miss is made of", "Effective miss 的組成")}</h3><p class="fig-sub" id="m2-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw open"></span>${L("dropped (never processed)", "dropped（從未處理）")}</span><span class="k"><span class="sw overshoot-sw"></span>${L("late (processed after the deadline)", "late（超過 deadline 才處理完）")}</span></div><div class="chart" id="m2"></div>
          <p class="fig-note">${L("Guard trades a few more drops for almost no late frames. Shares are of all published frames.", "Guard 多丟一些 frame，換來幾乎沒有 late frame。比例以所有 published frames 為分母。")}</p></div>
        <div class="span-6 fig"><div class="fig-head"><div class="titles"><h3>${L("Queueing: frame age when inference starts", "Queueing：inference 開始時的 frame age")}</h3><p class="fig-sub" id="m3-sub"></p></div></div><div class="chart" id="m3"></div>
          <p class="fig-note">${L("Queues that serve the oldest frame (FIFO, legacy depth 5) make every frame wait for the whole backlog under overload.", "處理最舊 frame 的 queue（FIFO、legacy depth 5）在過載時會讓每個 frame 都等完整個 backlog。")}</p></div>
      </div>
      <div class="fig section-gap"><div class="fig-head"><div class="titles"><h3>${L("Ablation: Adaptive − Deadline-Guard", "Ablation：Adaptive − Deadline-Guard")}</h3><p class="fig-sub" id="m4-sub"></p></div></div>
        <div class="chart" id="m4"></div><div id="m4-table"></div>
        <p class="fig-note">${L("The switch can only change a decision when ≥ 2 feasible frames are queued and estimated ρ &lt; 1. In these conditions the queue rarely holds two feasible frames, so EDF and newest-feasible pick the same frame.",
          "只有在 queue 中有 ≥ 2 個 feasible frames 且估計 ρ &lt; 1 時，switch 才可能改變決定。在這些 conditions 下 queue 很少同時有兩個 feasible frames，所以 EDF 與 newest-feasible 會選到同一個 frame。")}</p></div>
      ${dyn.condition ? `<div class="fig section-gap"><div class="fig-head"><div class="titles"><h3>${L("Dynamic load", "動態負載")}: ${esc(COND[dyn.condition].label)}</h3><p class="fig-sub">${L(`Effective miss per phase (20 s each) · mean and min–max over ${COND[dyn.condition].n_blocks} runs per arm`, `各 phase（各 20 秒）的 effective miss · 每個 arm ${COND[dyn.condition].n_blocks} runs 的平均與 min–max`)}</p></div></div>
        <div class="grid" id="m5"></div><div id="m5-table"></div></div>` : ""}`;

    // M1 feasibility
    C.hbars(sec.querySelector("#m1"), {
      // Below ρ = 1 the newest frame does not wait for the worker, so only the service time is drawn
      // (the same first-order model as the overview regime map).
      rows: Mx.feasibility.map((f) => ({ label: COND[f.condition].label, dim: !f.overloaded, segments: [
        { v: f.overloaded ? f.inter_arrival_ms : 0, open: true, name: "inter-arrival" }, { v: f.service_ms, color: "var(--ink)", name: "service" }],
        valueText: `${fmt(f.overloaded ? f.age_bound_ms : f.service_ms, 0)} ms`, valueNote: f.overloaded ? "" : L("not overloaded: no waiting", "未過載：不需等待"),
        tip: tipRows(COND[f.condition].label, [["inter-arrival", fmt(f.inter_arrival_ms, 1) + " ms"], ["service (Latest)", fmt(f.service_ms, 1) + " ms"], [L("sum", "合計"), fmt(f.age_bound_ms, 1) + " ms"], ["ρ", fmt(f.utilization, 2)], [L("overloaded", "過載"), f.overloaded ? L("yes", "是") : L("no", "否")]]) })),
      refs: [{ value: Mx.feasibility[0].deadline_ms, label: `deadline ${fmt(Mx.feasibility[0].deadline_ms, 0)} ms` }], xTitle: L("Milliseconds", "毫秒"), rowH: 44, ariaLabel: L("Inter-arrival plus service time versus deadline", "Inter-arrival + service time vs deadline"),
    });
    sec.querySelector("#m1-table").innerHTML = table(
      [{ label: "Condition", l: true }, { label: "ρ" }, { label: "Regime", l: true, wrap: true }, { label: L("Predicted Latest late %", "預測 Latest late %") }, { label: L("Observed Latest late %", "實測 Latest late %") }, { label: L("Observed Guard late %", "實測 Guard late %") }, { label: L("Guard − Latest Δ pp [95% CI] · blocks lower", "Guard − Latest Δ pp [95% CI] · 較低的 blocks"), wrap: true }],
      Mx.feasibility.map((f) => ({ hl: f.condition === D.primary_condition, cells: [esc(COND[f.condition].label), fmt(f.utilization, 2), esc(T(f, "regime")), fmt(f.predicted_latest_late_pct, 1), fmt(f.observed_latest_deadline_miss_pct, 1), fmt(f.observed_guard_deadline_miss_pct, 1),
        `${fmt(f.guard_minus_latest_eff_pp.mean, 2, true)} ${ci(f.guard_minus_latest_eff_pp, 2)} · ${f.guard_minus_latest_eff_pp.n_neg}/${COND[f.condition].n_blocks}`] })));

    const ctl = sec.querySelector("#m-controls");
    control(ctl, "Condition", seg("Condition", fixed.map((c) => ({ value: c.id, label: c.label, html: esc(c.label) + (c.primary ? '<span class="star">primary</span>' : "") })), state.mc, (v) => { state.mc = v; setParams("mechanism", { mc: v }); drawCond(); }));

    function drawCond() {
      const cid = state.mc, c = COND[cid];
      const order = [...APP_ORDER, ...LEGACY_ORDER];
      const groupName = (id) => (ARM[id].family === "legacy" ? L("Legacy path", "Legacy 路徑") : "Application queue");
      sec.querySelector("#m2-sub").textContent = L(`${c.label} · mean over ${c.n_blocks} runs per arm`, `${c.label} · 每個 arm ${c.n_blocks} runs 的平均`);
      C.hbars(sec.querySelector("#m2"), {
        max: 100,
        rows: order.map((id) => { const r = armRow(cid, id);
          const drop = r.drop_rate_pct.mean, late = Math.max(0, r.late_share_pct);
          return { group: groupName(id), label: ARM[id].label, dim: ARM[id].family === "legacy",
            segments: [{ v: drop, open: true, name: "dropped" }, { v: late, late: true, name: "late" }],
            valueText: fmt(r.effective_miss_rate_pct.mean, 1) + "%",
            tip: tipRows(`${ARM[id].label} · ${c.label}`, [["dropped", fmt(drop, 1) + "%"], ["late", fmt(late, 1) + "%"], ["effective miss", fmt(r.effective_miss_rate_pct.mean, 1) + "%"], ["policy drops", fmt(r.app_policy_drop_rate_pct.mean, 1) + "%"], [L("DDS-unreceived / run", "DDS 未收到 / run"), fmt(r.dds_unreceived_frames.mean, 0)]]) }; }),
        xTitle: L("% of published frames", "占 published frames 的 %"), ariaLabel: L("Dropped and late share by arm", "各 arm 的 dropped 與 late 比例"),
      });
      sec.querySelector("#m3-sub").textContent = L(`${c.label} · median age of a frame when its inference starts`, `${c.label} · inference 開始時 frame age 的中位數`);
      C.hbars(sec.querySelector("#m3"), {
        rows: order.map((id) => { const r = armRow(cid, id);
          return { group: groupName(id), label: ARM[id].label, dim: ARM[id].family === "legacy",
            segments: [{ v: r.p50_frame_age_at_start_ms.mean, color: ARM[id].color }], valueText: `${fmt(r.p50_frame_age_at_start_ms.mean, 0)} ms`,
            tip: tipRows(`${ARM[id].label} · ${c.label}`, [[L("P50 frame age at start", "開始時 P50 frame age"), fmt(r.p50_frame_age_at_start_ms.mean, 1) + " ms"], ["mean queue wait", r.avg_queue_wait_ms.mean === null ? L("n/a (no app queue)", "n/a（無 app queue）") : fmt(r.avg_queue_wait_ms.mean, 1) + " ms"], ["max queue length", r.max_queue_len.mean === null ? "n/a" : fmt(r.max_queue_len.max, 0)], ["P50 latency", fmt(r.p50_latency_ms.mean, 1) + " ms"]]) }; }),
        refs: [{ value: c.deadline_ms, label: "deadline" }], xTitle: L("Milliseconds", "毫秒"), ariaLabel: L("Frame age at inference start by arm", "各 arm 在 inference 開始時的 frame age"),
      });
    }
    drawCond();

    // M4 ablation
    const abl = S.conditions.map((c) => ({ c, p: pairRow(c.id, "adaptive_c5_q10", "guard_c5_q10") }));
    const phaseName = (ph) => ["phase 1 · 10 FPS", "phase 2 · 20 FPS", "phase 3 · 10 FPS"][ph] || `phase ${ph + 1}`;
    const dynRows = (dyn.paired || []).filter((p) => p.arm === "adaptive_c5_q10" && p.reference === "guard_c5_q10" && p.phase > 0);
    sec.querySelector("#m4-sub").textContent = L(
      `Δ effective miss (pp), within-block · every fixed-rate condition${dynRows.length ? ` and ${dynRows.map((p) => phaseName(p.phase)).join(", ")} of the dynamic run` : ""} · Adaptive = Guard + utilisation switch`,
      `Δ effective miss (pp)，block 內比較 · 所有固定速率 condition${dynRows.length ? `，以及 dynamic run 的 ${dynRows.map((p) => phaseName(p.phase)).join("、")}` : ""} · Adaptive = Guard + utilisation switch`);
    const ofBlocks = (e, n) => L(`${e.n_neg}↓ ${e.n_pos}↑ of ${n}`, `${n} 中 ${e.n_neg}↓ ${e.n_pos}↑`);
    const frows = abl.map(({ c, p }) => { const e = p.metrics.effective_miss_rate_pct;
      return { group: L("Whole run", "整個 run"), label: c.label, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM.adaptive_c5_q10.color,
        sub: `${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${ofBlocks(e, p.n_blocks)}`,
        tip: tipRows(`Adaptive − Guard · ${c.label}`, [["mean Δ", fmt(e.mean, 2, true) + " pp"], ["95% CI", ci(e, 2)], [L("blocks lower / higher", "blocks 較低 / 較高"), `${e.n_neg} / ${e.n_pos}`], ["sign-flip p", fmt(e.signflip_p, 3)]]) }; })
      .concat(dynRows.map((p) => { const e = p.metrics.effective_miss_pct;
        return { group: L("Dynamic run · per phase", "Dynamic run · 各 phase"), label: phaseName(p.phase), mean: e.mean, lo: e.lo, hi: e.hi, color: ARM.adaptive_c5_q10.color,
          sub: `${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${ofBlocks(e, p.n_blocks)}`,
          tip: tipRows(`Adaptive − Guard · ${phaseName(p.phase)}`, [["mean Δ", fmt(e.mean, 2, true) + " pp"], ["95% CI", ci(e, 2)], ["blocks", p.n_blocks]]) }; }));
    C.forest(sec.querySelector("#m4"), { rows: frows, xTitle: "Δ effective miss (pp) · Adaptive − Deadline-Guard", ariaLabel: L("Ablation forest plot", "Ablation forest plot") });
    const decKeys = (o) => Object.entries(o).map(([k, v]) => `${esc(k)} ${fmt(v, 0)}`).join(" · ") || "—";
    sec.querySelector("#m4-table").innerHTML = table(
      [{ label: "Condition", l: true }, { label: "Adaptive decisions / run", l: true }, { label: "Deadline-Guard decisions / run", l: true }, { label: "Adaptive drops / run", l: true }, { label: "Guard drops / run", l: true }],
      S.conditions.map((c) => { const a = Mx.decisions.find((d) => d.condition === c.id && d.arm === "adaptive_c5_q10"), gd = Mx.decisions.find((d) => d.condition === c.id && d.arm === "guard_c5_q10");
        return { cells: [esc(c.label), decKeys(a.decisions), decKeys(gd.decisions), decKeys(a.policy_drops), decKeys(gd.policy_drops)] }; }),
      { toggle: L("Scheduler decision counts (mean per run, from the detector logs)", "Scheduler 決策次數（每個 run 的平均，取自 detector log）") });

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
              tip: tipRows(`${ARM[id].label} · ${phaseName(ph)}`, [["effective miss", `${fmt(st.mean, 1)}% (${fmt(st.min, 1)}–${fmt(st.max, 1)})`], ["on-time FPS", fmt(p.on_time_fps.mean, 2)], ["P99", fmt(p.p99_latency_ms.mean, 1) + " ms"], ...(p.transient_effective_miss_pct.mean !== null ? [[L("first 3 s after step", "階躍後前 3 秒"), fmt(p.transient_effective_miss_pct.mean, 1) + "%"]] : [])]) }; }),
          xTitle: "Effective miss (%)", ariaLabel: `Dynamic ${phaseName(ph)}` });
      });
      sec.querySelector("#m5-table").innerHTML = table(
        [{ label: "Arm", l: true }, ...phases.map((ph) => ({ label: `${phaseName(ph)} eff. %` })), { label: L("Step-up first 3 s eff. %", "升載後前 3 秒 eff. %") }, { label: L("Step-down first 3 s eff. %", "降載後前 3 秒 eff. %") }, { label: "Phase 2 P99 ms" }],
        [...APP_ORDER, ...LEGACY_ORDER].map((id) => { const ps = phases.map((ph) => dyn.phases.find((x) => x.phase === ph && x.arm === id));
          return { hl: id === "guard_c5_q10" || id === "adaptive_c5_q10", cells: [sw(ARM[id].color) + esc(ARM[id].label), ...ps.map((p) => fmt(p.effective_miss_pct.mean, 1)),
            fmt(ps[1] && ps[1].transient_effective_miss_pct.mean, 1), fmt(ps[2] && ps[2].transient_effective_miss_pct.mean, 1), fmt(ps[1] && ps[1].p99_latency_ms.mean, 1)] }; }),
        { toggle: L("Per-phase table and step transients", "各 phase 數據表與階躍暫態") });
    }
  }

  X.views.mechanism = renderMechanism;
})();
