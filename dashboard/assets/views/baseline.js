/* Baseline view: capacity, queueing and overload of the legacy path. Numbers come from window.DASHBOARD_DATA through window.Dash (assets/app.js).
 * Text is written as L(english, traditional_chinese); see assets/i18n.js. */
(function () {
  "use strict";
  const X = window.Dash;
  if (!X) return;
  const { D, C, L, T, fmt, esc, S, ARM, COND, MODEL, MODEL_COLOR, APP_ORDER, LEGACY_ORDER, METRICS, betterText,
    armRow, pairRow, runsOf, blockNo, ci, tipRows, sw, blockDiffs, state, setParams, seg, control, table, spec, condOptions } = X;

  function renderBaseline(sec) {
    const B = D.baseline;
    const cap = B.capacity, dm = B.drop_model;
    sec.innerHTML = `
      <div class="view-head"><h2>${L("Baseline performance: capacity, queueing and overload", "Baseline 效能：capacity、queueing 與 overload")}</h2>
      <p>${L(`${B.n_runs} constrained runs over ${B.n_conditions} conditions (3 runs each): input rate, subscriber queue depth and injected service delay. Every run uses the legacy path (inference in the DDS callback).`,
        `${B.n_conditions} 個 conditions 共 ${B.n_runs} 個 constrained runs（每個 3 runs），變因為 input rate、subscriber queue depth 與注入的 service delay。所有 run 都走 legacy 路徑（在 DDS callback 內執行 inference）。`)}</p></div>
      <div class="controls" id="b-controls"></div>
      ${spec([
        { label: L("MobileViT-S saturated throughput", "MobileViT-S 飽和 throughput"), value: fmt(cap.mobilevit_s.mean, 1), unit: "FPS", detail: `${fmt(cap.mobilevit_s.min, 1)}–${fmt(cap.mobilevit_s.max, 1)}, n=${cap.mobilevit_s.n_runs} runs · service ${fmt(cap.mobilevit_s.service_ms_mean, 1)} ms` },
        { label: L("MobileViT-XXS saturated throughput", "MobileViT-XXS 飽和 throughput"), value: fmt(cap.mobilevit_xxs.mean, 1), unit: "FPS", detail: `${fmt(cap.mobilevit_xxs.min, 1)}–${fmt(cap.mobilevit_xxs.max, 1)}, n=${cap.mobilevit_xxs.n_runs} runs · service ${fmt(cap.mobilevit_xxs.service_ms_mean, 1)} ms` },
        { label: L("Worst drop rate below capacity (ρ &lt; 1)", "未達 capacity 時最差的 drop rate（ρ &lt; 1）"), value: fmt(dm.below_capacity_max_drop_pct, 2), unit: "%", detail: L(`worst of ${dm.below_capacity_runs} runs with ρ &lt; 1: almost every frame was delivered and processed`, `ρ &lt; 1 的 ${dm.below_capacity_runs} 個 runs 中最差者：幾乎每個 frame 都送達並處理完成`) },
        { label: L("Overload drops vs 1 − 1/ρ", "過載 drop vs 1 − 1/ρ"), value: fmt(dm.overloaded_mean_abs_gap_pp, 2), unit: L("pp mean gap", "pp 平均差距"), detail: L(`max ${fmt(dm.overloaded_max_abs_gap_pp, 2)} pp over ${dm.overloaded_runs} overloaded runs`, `${dm.overloaded_runs} 個過載 runs 中最大 ${fmt(dm.overloaded_max_abs_gap_pp, 2)} pp`) },
      ])}
      <div class="grid section-gap">
        <div class="span-6 fig"><div class="fig-head"><div class="titles"><h3>${L("Throughput saturates at the service-time limit", "Throughput 在 service time 上限處飽和")}</h3><p class="fig-sub">${L("Processed vs offered FPS · input-rate sweep (depth 5, no delay) · mean of 3 runs", "Processed vs offered FPS · input-rate sweep（depth 5，無 delay）· 3 runs 平均")}</p></div>${X.MEAS}</div><div class="legend" id="b1-legend"></div><div class="chart" id="b1"></div></div>
        <div class="span-6 fig"><div class="fig-head"><div class="titles"><h3>${L("Drops follow the overload model 1 − 1/ρ", "Drop 符合過載模型 1 − 1/ρ")}</h3><p class="fig-sub">${L("Every baseline run · measured drop rate vs prediction from offered rate × service time", "每個 baseline run · 實測 drop rate vs 由 offered rate × service time 推得的預測值")}</p></div>${X.MEAS}</div><div class="legend" id="b2-legend"></div><div class="chart" id="b2"></div></div>
        <div class="span-6 fig"><div class="fig-head"><div class="titles"><h3>${L("Under overload, queue depth sets the latency", "過載時，queue depth 決定 latency")}</h3><p class="fig-sub">${L("P50 end-to-end latency at 20 FPS by KEEP_LAST depth · bar = mean, tick = P99 · 3 runs each", "20 FPS 下各 KEEP_LAST depth 的 P50 end-to-end latency · 長條 = 平均，刻線 = P99 · 各 3 runs")}</p></div>${X.MEAS}</div><div class="chart" id="b3"></div>
        <p class="fig-note">${L("The single-threaded detector always serves the oldest of the <i>depth</i> frames DDS keeps, so queue wait ≈ depth / input rate once the detector is saturated.", "單執行緒的 detector 永遠處理 DDS 保留的 <i>depth</i> 個 frame 中最舊的那個，所以 detector 飽和後，queue wait ≈ depth / input rate。")}</p></div>
        <div class="span-6 fig"><div class="fig-head"><div class="titles"><h3>${L("Injected service delay pushes both models into overload", "注入 service delay 讓兩個模型都進入過載")}</h3><p class="fig-sub">${L("Effective miss vs artificial delay added to each inference · 20 FPS, depth 5", "Effective miss vs 每次 inference 額外加入的 artificial delay · 20 FPS，depth 5")}</p></div>${X.MEAS}</div><div class="legend" id="b4-legend"></div><div class="chart" id="b4"></div></div>
      </div>
      <div class="section-gap" id="b-table"></div>`;

    const ctl = sec.querySelector("#b-controls");
    control(ctl, L("Model", "模型"), seg(L("Model", "模型"), [{ value: "both", label: L("Both", "兩者") }, { value: "mobilevit_s", label: "MobileViT-S" }, { value: "mobilevit_xxs", label: "MobileViT-XXS" }], state.model, (v) => {
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
        series: models.map((m) => ({ name: MODEL[m], color: MODEL_COLOR[m],
          points: conds.filter((c) => c.family === "fps" && c.model === m).map((c) => ({ x: c.offered_fps.mean, y: c.processed_fps.mean, tip: condTip(c) })) })),
        diag: "processed = offered", xTitle: "Offered FPS", yTitle: "Processed FPS", endLabels: true, ariaLabel: L("Processed versus offered frames per second", "Processed vs offered FPS"),
      });
      const runs = B.runs.filter((r) => models.includes(r.model));
      C.lineChart(sec.querySelector("#b2"), {
        scatter: true,
        series: models.map((m) => ({ name: MODEL[m], color: MODEL_COLOR[m],
          points: runs.filter((r) => r.model === m && r.expected_overload_drop_pct !== null).map((r) => ({ x: r.expected_overload_drop_pct, y: r.drop_rate_pct,
            tip: tipRows(r.run_id.replace(/_normal|_mobilevit/g, ""), [[L("predicted 1 − 1/ρ", "預測 1 − 1/ρ"), fmt(r.expected_overload_drop_pct, 1) + "%"], [L("measured drop", "實測 drop"), fmt(r.drop_rate_pct, 1) + "%"], ["ρ", fmt(r.utilization, 2)], ["depth", r.qos_depth], ["delay", r.delay_ms + " ms"]]) })) })),
        diag: L("measured = predicted", "實測 = 預測"), xTitle: L("Predicted drop 100·(1 − 1/ρ) (%)", "預測 drop 100·(1 − 1/ρ) (%)"), yTitle: L("Measured drop (%)", "實測 drop (%)"), ariaLabel: L("Measured versus predicted drop rate per run", "每個 run 的實測 vs 預測 drop rate"),
      });
      const q = conds.filter((c) => c.family === "qos").sort((a, b) => (a.model > b.model ? 1 : -1) || a.qos_depth - b.qos_depth);
      C.hbars(sec.querySelector("#b3"), {
        rows: q.map((c) => ({ group: models.length > 1 ? MODEL[c.model] : undefined, label: `depth ${c.qos_depth}`,
          segments: [{ v: c.p50_latency_ms.mean, color: MODEL_COLOR[c.model] }], marker: c.p99_latency_ms.mean,
          valueText: `${fmt(c.p50_latency_ms.mean, 0)} ms`, tip: condTip(c) })),
        refs: [{ value: 100, label: "deadline 100 ms" }], xTitle: "Latency (ms)", ariaLabel: L("P50 latency by queue depth", "各 queue depth 的 P50 latency"),
      });
      C.lineChart(sec.querySelector("#b4"), {
        series: models.map((m) => ({ name: MODEL[m], color: MODEL_COLOR[m],
          points: conds.filter((c) => c.family === "overload" && c.model === m).map((c) => ({ x: c.delay_ms, y: c.effective_miss_rate_pct.mean, tip: condTip(c, [["delay", c.delay_ms + " ms"]]) })) })),
        xTitle: L("Artificial delay per frame (ms)", "每個 frame 的 artificial delay (ms)"), yTitle: "Effective miss (%)", endLabels: true, yMax: 100, ariaLabel: L("Effective miss versus artificial delay", "Effective miss vs artificial delay"),
      });
      sec.querySelector("#b-table").innerHTML = table(
        [{ label: L("Family", "類別"), l: true }, { label: L("Model", "模型"), l: true }, { label: "FPS" }, { label: "Depth" }, { label: "Delay ms" }, { label: "n" }, { label: "Processed FPS" }, { label: "ρ" }, { label: "Drop %" }, { label: "1−1/ρ %" }, { label: "Deadline miss %" }, { label: "Eff. miss %" }, { label: "P50 ms" }, { label: "P99 ms" }, { label: "Inference ms" }, { label: "Detector CPU %" }, { label: "Max RSS MB" }, { label: "cgroup peak MB" }, { label: L("Drop cause", "Drop 原因"), l: true }],
        conds.map((c) => ({ cells: [c.family, MODEL[c.model], fmt(c.input_fps, 0), c.qos_depth, c.delay_ms, c.n_runs,
          `${fmt(c.processed_fps.mean, 2)} ± ${fmt(c.processed_fps.sd, 2)}`, fmt(c.utilization.mean, 2), fmt(c.drop_rate_pct.mean, 2), fmt(c.expected_overload_drop_pct.mean, 2),
          fmt(c.deadline_miss_rate_pct.mean, 1), fmt(c.effective_miss_rate_pct.mean, 1), fmt(c.p50_latency_ms.mean, 1), fmt(c.p99_latency_ms.mean, 1),
          fmt(c.avg_inference_ms.mean, 1), fmt(c.detector_cpu_pct.mean, 0), fmt(c.max_memory_mb.mean, 0), fmt(c.cgroup_memory_peak_mb.mean, 0), esc(c.drop_cause)] })),
        { toggle: L(`All ${conds.length} baseline conditions (mean ± SD across runs)`, `全部 ${conds.length} 個 baseline conditions（各 runs 的 mean ± SD）`) });
    }
    draw();
  }

  X.views.baseline = renderBaseline;
})();
