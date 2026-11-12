/* Dashboard views. All numbers come from window.DASHBOARD_DATA (src/dashboard/build_data.py).
 * Text is written as L(english, traditional_chinese); see assets/i18n.js. */
(function () {
  "use strict";
  const D = window.DASHBOARD_DATA;
  const C = window.Charts;
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
  const ARM = {}; D.arms.forEach((a) => { ARM[a.id] = Object.assign({ color: `var(--s${a.slot})` }, a); });
  const S = D.scheduling;
  const COND = {}; S.conditions.forEach((c) => { COND[c.id] = c; });
  const MODEL = { mobilevit_s: "MobileViT-S", mobilevit_xxs: "MobileViT-XXS" };
  const MODEL_COLOR = { mobilevit_s: "var(--s1)", mobilevit_xxs: "var(--s2)" };
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
    document.title = { overview: "OS-Aware Edge AI Runtime", baseline: L("Baseline", "基準測試") + " · OS-Aware Edge AI Runtime", scheduling: L("Scheduling", "排程比較") + " · OS-Aware Edge AI Runtime", mechanism: L("Mechanism", "運作機制") + " · OS-Aware Edge AI Runtime", evidence: L("Evidence", "驗證證據") + " · OS-Aware Edge AI Runtime" }[view];
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
  const condOptions = () => S.conditions.map((c) => ({ value: c.id, label: c.label, html: esc(c.label) + (c.primary ? `<span class="star" title="${L("primary condition, fixed in the analysis plan before the formal runs", "primary condition，正式 run 之前已在分析計畫中固定")}">primary</span>` : "") }));

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
    const dl = fmt(pc.deadline_ms, 0);
    const archSvg = L("assets/architecture.svg", "assets/architecture_zh.svg");
    sec.innerHTML = `
      <div class="hero">
        <div>
          <h2>${L("Which frames should an overloaded edge detector skip?", "過載的邊緣偵測器該跳過哪些 frame？")}</h2>
          <p class="lede">${L("A measured ROS 2 benchmark of frame-scheduling policies for a MobileViT detector on a constrained Linux host: two pinned CPU cores, a 4 GiB memory limit and a Fast DDS shared-memory transport verified on every run.",
            "在受限 Linux 主機上，針對 MobileViT 偵測器實測各種 frame scheduling policy 的 ROS 2 benchmark：綁定 2 顆 CPU core、4 GiB 記憶體上限，且每個 run 都驗證 Fast DDS shared-memory transport 確實生效。")}</p>
          <p class="answer">${L(`Skipping frames that are predicted to miss the ${dl} ms deadline (<b>Deadline-Guard</b>) lowers the effective miss rate by <b>${fmt(-g.mean, 1)} pp</b> against Latest-Frame at ${esc(pc.label)}. <b>Adaptive</b>, which adds a utilisation switch on top, lands in the same place: no measurable difference from Deadline-Guard.`,
            `丟棄預測會錯過 ${dl} ms deadline 的 frame（<b>Deadline-Guard</b>），在 ${esc(pc.label)} 下比 Latest-Frame 降低 effective miss rate <b>${fmt(-g.mean, 1)} pp</b>。在此之上再加 utilisation switch 的 <b>Adaptive</b> 結果相同：與 Deadline-Guard 沒有可量測的差異。`)}</p>
          <div class="links"><a href="#scheduling">${L("Compare all six policies", "比較全部六種 policy")}</a><a href="#mechanism">${L("Why it works", "為什麼有效")}</a><a href="#evidence">${L("How the data is verified", "資料如何驗證")}</a></div>
        </div>
        <div class="panel hero-chart">
          <div class="result" aria-label="${L("Main result", "主要結果")}">
            <p class="result-cap">${L(`Effective miss at ${esc(pc.label)} · ρ ≈ ${fmt(lat.utilization.mean, 2)} (overloaded) · ${dl} ms deadline · lower is better`,
              `${esc(pc.label)} 的 effective miss · ρ ≈ ${fmt(lat.utilization.mean, 2)}（過載）· ${dl} ms deadline · 越低越好`)}</p>
            <div class="result-row">
              <div class="r-item"><span class="r-label">${sw(ARM.latest_q10.color)}Latest-Frame</span><span class="r-v">${fmt(lat.effective_miss_rate_pct.mean, 1)}%</span></div>
              <svg class="r-arrow" viewBox="0 0 40 16" aria-hidden="true"><path d="M2 8h33M29 3l6 5-6 5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <div class="r-item"><span class="r-label">${sw(ARM.guard_c5_q10.color)}Deadline-Guard</span><span class="r-v">${fmt(grd.effective_miss_rate_pct.mean, 1)}%</span></div>
              <div class="r-item r-peer"><span class="r-label">${sw(ARM.adaptive_c5_q10.color)}Adaptive</span><span class="r-v">${fmt(ada.effective_miss_rate_pct.mean, 1)}%</span></div>
            </div>
            <p class="r-diff">${L(`<b>${fmt(g.mean, 2)} pp</b> paired difference (Deadline-Guard − Latest-Frame) · 95% CI ${ci(g, 2)} · lower in ${g.n_neg} of ${g.n_blocks} blocks`,
              `paired difference（Deadline-Guard − Latest-Frame）<b>${fmt(g.mean, 2)} pp</b> · 95% CI ${ci(g, 2)} · ${g.n_blocks} 個 blocks 中有 ${g.n_neg} 個較低`)}</p>
          </div>
          <hr class="fig-divider">
          <div class="fig-head"><div class="titles"><h3>${L("Every run", "每一個 run")}</h3>
            <p class="fig-sub">${L(`Dropped + late frames, % of published · same application architecture · ${pc.n_blocks} runs per policy`,
              `Dropped + late frames 占 published 的 % · 相同 application architecture · 每個 policy ${pc.n_blocks} 個 runs`)}</p></div></div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>${L("one run", "單一 run")}</span><span class="k"><span class="sw tick"></span>${L("mean", "平均")}</span></div>
          <div class="chart" id="hero-dots"></div>
          <hr class="fig-divider">
          <div class="fig-head"><div class="titles"><h3>${L("Paired difference within blocks", "Block 內的 paired difference")}</h3>
            <p class="fig-sub">${L(`Mean and 95% interval over ${g.n_blocks} blocks · open circles are single blocks`, `${g.n_blocks} 個 blocks 的平均與 95% 區間 · 空心圓為單一 block`)}</p></div></div>
          <div class="chart" id="hero-forest"></div>
          <p class="fig-note">${L(`One host, n = ${g.n_blocks} blocks for this condition, latency only (random-initialised weights). Adaptive − Deadline-Guard includes 0, which is not an equivalence test. <a href="#evidence">Limitations</a>`,
            `單一主機，此 condition n = ${g.n_blocks} blocks，只量 latency（random-initialised weights）。Adaptive − Deadline-Guard 的區間包含 0，但這不是 equivalence test。<a href="#evidence">使用限制</a>`)}</p>
        </div>
      </div>

      <div class="stat-row">
        <div class="stat"><div class="label">Adaptive − Latest-Frame · ${esc(pc.label)}</div><div class="v">${fmt(al.mean, 1)}<span class="unit">pp</span></div><div class="d">${L(`95% CI ${ci(al, 2)} · ${al.n_neg}/${al.n_blocks} blocks lower`, `95% CI ${ci(al, 2)} · ${al.n_neg}/${al.n_blocks} blocks 較低`)}</div></div>
        ${gd ? `<div class="stat"><div class="label">${L(`Guard − Latest under a load step · ${esc(COND[gd.condition].label)}`, `負載階躍下的 Guard − Latest · ${esc(COND[gd.condition].label)}`)}</div><div class="v">${fmt(gd.mean, 1)}<span class="unit">pp</span></div><div class="d">95% CI ${ci(gd, 2)} · Adaptive − Guard ${fmt(agd.mean, 2, true)} pp</div></div>` : ""}
        <div class="stat"><div class="label">${L("Saturated throughput", "飽和 throughput")}</div><div class="v">${fmt(cap.mobilevit_s.mean, 1)}<span class="unit">FPS (S)</span></div><div class="d">${L(`MobileViT-XXS ${fmt(cap.mobilevit_xxs.mean, 1)} FPS · overloaded runs, n=${cap.mobilevit_s.n_runs} / ${cap.mobilevit_xxs.n_runs}`, `MobileViT-XXS ${fmt(cap.mobilevit_xxs.mean, 1)} FPS · 過載 runs，n=${cap.mobilevit_s.n_runs} / ${cap.mobilevit_xxs.n_runs}`)}</div></div>
        <div class="stat"><div class="label">${L("Constrained runs", "Constrained runs")}</div><div class="v">${K.runs.total}</div><div class="d">${L(`${K.runs.phase2} baseline + ${K.runs.phase3} A/B in ${K.runs.phase3_blocks} blocks · ${chain} file hashes verified`, `${K.runs.phase2} baseline + ${K.runs.phase3} A/B（${K.runs.phase3_blocks} blocks）· 已驗證 ${chain} 個檔案 hash`)}</div></div>
      </div>

      <section class="section">
        <div class="section-head"><div><h3>${L("The system", "系統架構")}</h3>
          <p>${L("One detector, one worker, a bounded queue in front of it, and a policy that decides which frame runs next.", "一個 detector、一個 worker、前面一個 bounded queue，再加上一個決定下一個要處理哪個 frame 的 policy。")}</p></div></div>
        <div class="prose-cols">
          <div><h4>${L("Problem", "問題")}</h4><p>${L(`MobileViT-S saturates at about ${fmt(cap.mobilevit_s.mean, 0)} FPS on two cores. When frames arrive faster, some must be skipped. Always running the newest frame can still spend inference time on frames that then finish after the ${dl} ms deadline.`,
            `MobileViT-S 在兩顆 core 上約 ${fmt(cap.mobilevit_s.mean, 0)} FPS 就飽和。frame 進來得更快時，一定要跳過一部分。即使永遠處理最新的 frame，仍可能把 inference 時間花在最後超過 ${dl} ms deadline 才完成的 frame 上。`)}</p></div>
          <div><h4>${L("Approach", "做法")}</h4><p>${L("FIFO, Latest-Frame, Deadline-Guard and Adaptive share one application queue and one inference worker, so differences between them are policy effects. Deadline-Guard predicts, before inference, whether a frame can still meet its deadline; Adaptive adds a utilisation switch.",
            "FIFO、Latest-Frame、Deadline-Guard 與 Adaptive 共用同一個 application queue 與同一個 inference worker，所以它們之間的差異就是 policy 的效果。Deadline-Guard 在 inference 之前預測 frame 是否還趕得上 deadline；Adaptive 則再加上 utilisation switch。")}</p></div>
          <div><h4>${L("Evidence", "證據")}</h4><p>${L("Policies run interleaved in blocks under identical controls and are compared within each block. Every table on this site is rebuilt from raw per-frame logs and checked against SHA-256 manifests before the page is generated.",
            "各 policy 在相同控制條件下以 block 交錯執行，並在每個 block 內比較。網站上的每張表都從原始 per-frame log 重建，並在產生頁面前與 SHA-256 manifest 核對。")}</p></div>
        </div>
        <div class="panel arch-panel"><div class="arch-scroll"><a href="${archSvg}" target="_blank" rel="noopener" class="arch-link" title="${L("Open the full-size diagram", "開啟完整尺寸架構圖")}">
          <img class="arch" src="${archSvg}" alt="${L("Architecture: image_stream_node publishes frames over Fast DDS shared memory to the MobileViT detector node. The legacy path runs inference in the DDS callback; the application path puts frames in a bounded queue served by one worker using FIFO, Latest-Frame, Deadline-Guard or Adaptive. Each run writes detector and publisher CSVs, metadata and a runtime probe; analysis tools build summaries and aggregates with SHA-256 manifests; provenance gates and the dashboard builder verify the chain. Separately, the EDA-Lite simulator turns simplified model profiles into cost-model estimates.",
            "架構圖：image_stream_node 透過 Fast DDS shared memory 把 frame 送到 MobileViT detector node。Legacy 路徑在 DDS callback 內執行 inference；application 路徑把 frame 放進 bounded queue，由一個 worker 依 FIFO、Latest-Frame、Deadline-Guard 或 Adaptive 處理。每個 run 會寫出 detector 與 publisher CSV、metadata 和 runtime probe；分析工具產生帶 SHA-256 manifest 的 summary 與 aggregate；provenance gate 與 dashboard builder 驗證整條鏈。另外，EDA-Lite simulator 把簡化的 model profile 轉成 cost-model 估計值。")}">
        </a></div><p class="arch-open"><a href="${archSvg}" target="_blank" rel="noopener">${L("Open the full-size diagram", "開啟完整尺寸架構圖")}</a><span class="arch-hint">${L(" · or scroll sideways", " · 或左右捲動")}</span></p></div>
      </section>

      <section class="section">
        <div class="section-head"><div><h3>${L("Findings", "研究發現")}</h3>
          <p>${L("Each answer is generated from the result tables when the dashboard is built.", "每個回答都是在建置 dashboard 時從結果表格自動產生的。")}</p></div></div>
        <div class="grid">
          <div class="span-7">
            <ol class="qlist">
              <li><div class="q">${L("Where does the pipeline saturate, and why are frames lost?", "Pipeline 在哪裡飽和？frame 為什麼會遺失？")}</div><div class="a">${esc(T(F.capacity, "text"))}</div></li>
              <li><div class="q">${L(`Which policy keeps the most frames inside a ${dl} ms deadline under overload?`, `過載時，哪個 policy 能讓最多 frame 在 ${dl} ms deadline 內完成？`)}</div><div class="a">${esc(T(F.guard, "text"))}</div></li>
              <li><div class="q">${L("Does Adaptive's utilisation switch add anything beyond the deadline check?", "Adaptive 的 utilisation switch 在 deadline 檢查之外還有額外效益嗎？")}</div><div class="a">${esc(T(F.adaptive, "text"))}</div></li>
            </ol>
          </div>
          <div class="span-5">
            <ul class="findings" style="grid-template-columns:1fr">
              ${["regime", "dynamic"].filter((k) => F[k]).map((k) => `<li><div class="t">${esc(T(F[k], "title"))}</div><div class="x">${esc(T(F[k], "text"))}</div></li>`).join("")}
              <li><div class="t">${L("Legacy comparisons are kept separate", "Legacy 比較分開呈現")}</div><div class="x">${L(`The legacy arms run inference inside the DDS callback, so differences against them mix architecture and policy and are never attributed to a policy. <a href="#scheduling">See paired differences</a>`,
                `Legacy arms 在 DDS callback 內執行 inference，所以與它們的差異混合了 architecture 與 policy 的效果，一律不歸因於 policy。<a href="#scheduling">查看 paired differences</a>`)}</div></li>
            </ul>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="section-head"><div><h3>${L("What the project contributes", "專案貢獻")}</h3></div></div>
        <ul class="contrib">
          <li><div class="t">${L("Constrained ROS 2 benchmark harness", "受限環境的 ROS 2 benchmark harness")} <span class="tag measured">${L("Measured", "實測")}</span></div><div class="x">${L(`CPU pinning, the memory limit and the shared-memory transport are read back from every run's metadata and runtime probe. ${K.runs.phase2} baseline runs map capacity, drops and queueing before any scheduling.`,
            `CPU pinning、記憶體上限與 shared-memory transport 都會從每個 run 的 metadata 與 runtime probe 讀回確認。在任何 scheduling 之前，先用 ${K.runs.phase2} 個 baseline runs 描繪 capacity、drop 與 queueing。`)}</div></li>
          <li><div class="t">${L("Deadline-feasibility scheduling with an ablation", "Deadline-feasibility scheduling 與 ablation")} <span class="tag measured">${L("Measured", "實測")}</span></div><div class="x">${L(`Four policies behind one bounded queue, plus two legacy arms, in ${K.runs.phase3} interleaved runs. Adaptive − Deadline-Guard isolates the utilisation switch.`,
            `同一個 bounded queue 後面的四種 policy，加上兩個 legacy arms，共 ${K.runs.phase3} 個交錯 runs。Adaptive − Deadline-Guard 用來單獨檢驗 utilisation switch 的效果。`)}</div></li>
          <li><div class="t">${L("Provenance-gated results", "Provenance 把關的結果")}</div><div class="x">${L(`Raw logs, tables and this dashboard are SHA-256 chained; pilot, unverified or example data stops the build. <a href="#evidence">Evidence</a>`,
            `原始 log、表格與這個 dashboard 以 SHA-256 串成一條鏈；只要混入 pilot、unverified 或 example 資料，建置就會中止。<a href="#evidence">驗證證據</a>`)}</div></li>
          <li><div class="t">${L("EDA-Lite layer-fusion simulator", "EDA-Lite layer-fusion simulator")} <span class="tag estimate">${L("Estimates", "估計值")}</span></div><div class="x">${L(`An offline cost model for simplified MobileViT profiles under SRAM budgets, in cost-model units and kept on its own page. Not linked to the runtime results. <a href="simulation.html">Simulation explorer</a>`,
            `針對簡化 MobileViT profile 在 SRAM 預算下的離線 cost model，單位是 cost-model units，放在獨立頁面，與 runtime 結果無關。<a href="simulation.html">模擬瀏覽器</a>`)}</div></li>
        </ul>
      </section>`;

    const heroArms = ["latest_q10", "guard_c5_q10", "adaptive_c5_q10"];
    C.dotRows(sec.querySelector("#hero-dots"), { valueW: 56, rowH: 32,
      rows: heroArms.map((id) => { const r = armRow(pc.id, id), st = r.effective_miss_rate_pct;
        return { label: ARM[id].label, color: ARM[id].color, mean: st.mean, min: st.min, max: st.max, valueText: fmt(st.mean, 1) + "%",
          points: runsOf(pc.id, id).map((x) => ({ v: x.effective_miss_rate_pct, label: `${ARM[id].label} block ${blockNo(x.block)}`,
            tip: tipRows(`${ARM[id].label} · block ${blockNo(x.block)}`, [["effective miss", fmt(x.effective_miss_rate_pct, 1) + "%"], ["drop", fmt(x.drop_rate_pct, 1) + "%"], [L("late (of processed)", "late（占 processed）"), fmt(x.deadline_miss_rate_pct, 1) + "%"]]) })),
          tip: tipRows(`${ARM[id].label} · ${pc.label}`, [["mean ± SD", `${fmt(st.mean, 1)} ± ${fmt(st.sd, 1)}%`], ["min – max", `${fmt(st.min, 1)} – ${fmt(st.max, 1)}%`], ["runs", r.n_runs]]) }; }),
      xTitle: "Effective miss (%)", ariaLabel: L("Effective miss for Latest-Frame, Deadline-Guard and Adaptive", "Latest-Frame、Deadline-Guard 與 Adaptive 的 effective miss") });
    const heroPairs = [["guard_c5_q10", "latest_q10", g], ["adaptive_c5_q10", "guard_c5_q10", ag]];
    C.forest(sec.querySelector("#hero-forest"), {
      rows: heroPairs.map(([a, ref, e]) => ({ label: `${ARM[a].label} − ${ARM[ref].label}`, mean: e.mean, lo: e.lo, hi: e.hi, color: ARM[a].color,
        sub: L(`${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${e.n_neg} of ${e.n_blocks} blocks lower`, `${fmt(e.mean, 2, true)} pp ${ci(e, 2)} · ${e.n_blocks} 個 blocks 中 ${e.n_neg} 個較低`),
        points: blockDiffs(pc.id, a, ref, "effective_miss_rate_pct", e, e.n_blocks, 2, " pp"),
        tip: tipRows(`${ARM[a].label} − ${ARM[ref].label}`, [["mean Δ", fmt(e.mean, 2, true) + " pp"], ["95% t-interval", ci(e, 2)], [L("blocks lower / higher", "blocks 較低 / 較高"), `${e.n_neg} / ${e.n_pos}`], ["sign-flip p", fmt(e.signflip_p, 3)]]) })),
      xTitle: "Δ effective miss (pp)", ariaLabel: L("Paired differences: Guard minus Latest, Adaptive minus Guard", "Paired differences：Guard − Latest、Adaptive − Guard") });
  }

  /* =============================== BASELINE =============================== */
  function renderBaseline(sec) {
    const B = D.baseline;
    const cap = B.capacity, dm = B.drop_model;
    sec.innerHTML = `
      <div class="view-head"><h2>${L("Baseline Performance: Capacity, Queueing, and Overload", "Baseline 效能：Capacity、Queueing 與 Overload")}</h2>
      <p>${L(`${B.n_runs} constrained runs over ${B.n_conditions} conditions (3 runs each): input rate, subscriber queue depth and injected service delay. Every run uses the legacy path (inference in the DDS callback).`,
        `${B.n_conditions} 個 conditions 共 ${B.n_runs} 個 constrained runs（每個 3 runs），變因為 input rate、subscriber queue depth 與注入的 service delay。所有 run 都走 legacy 路徑（在 DDS callback 內執行 inference）。`)}</p></div>
      <div class="controls" id="b-controls"></div>
      <div class="stat-row">
        <div class="stat"><div class="label">${L("MobileViT-S saturated throughput", "MobileViT-S 飽和 throughput")}</div><div class="v">${fmt(cap.mobilevit_s.mean, 1)}<span class="unit">FPS</span></div><div class="d">${fmt(cap.mobilevit_s.min, 1)}–${fmt(cap.mobilevit_s.max, 1)}, n=${cap.mobilevit_s.n_runs} runs · service ${fmt(cap.mobilevit_s.service_ms_mean, 1)} ms</div></div>
        <div class="stat"><div class="label">${L("MobileViT-XXS saturated throughput", "MobileViT-XXS 飽和 throughput")}</div><div class="v">${fmt(cap.mobilevit_xxs.mean, 1)}<span class="unit">FPS</span></div><div class="d">${fmt(cap.mobilevit_xxs.min, 1)}–${fmt(cap.mobilevit_xxs.max, 1)}, n=${cap.mobilevit_xxs.n_runs} runs · service ${fmt(cap.mobilevit_xxs.service_ms_mean, 1)} ms</div></div>
        <div class="stat"><div class="label">${L("Worst drop rate below capacity (ρ &lt; 1)", "未達 capacity 時最差的 drop rate（ρ &lt; 1）")}</div><div class="v">${fmt(dm.below_capacity_max_drop_pct, 2)}<span class="unit">%</span></div><div class="d">${L(`worst of ${dm.below_capacity_runs} runs with ρ &lt; 1: almost every frame was delivered and processed`, `ρ &lt; 1 的 ${dm.below_capacity_runs} 個 runs 中最差者：幾乎每個 frame 都送達並處理完成`)}</div></div>
        <div class="stat"><div class="label">${L("Overload drops vs 1 − 1/ρ", "過載 drop vs 1 − 1/ρ")}</div><div class="v">${fmt(dm.overloaded_mean_abs_gap_pp, 2)}<span class="unit">${L("pp mean gap", "pp 平均差距")}</span></div><div class="d">${L(`max ${fmt(dm.overloaded_max_abs_gap_pp, 2)} pp over ${dm.overloaded_runs} overloaded runs`, `${dm.overloaded_runs} 個過載 runs 中最大 ${fmt(dm.overloaded_max_abs_gap_pp, 2)} pp`)}</div></div>
      </div>
      <div class="grid section-gap">
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>${L("Throughput saturates at the service-time limit", "Throughput 在 service time 上限處飽和")}</h3><p class="fig-sub">${L("Processed vs offered FPS · input-rate sweep (depth 5, no delay) · mean of 3 runs", "Processed vs offered FPS · input-rate sweep（depth 5，無 delay）· 3 runs 平均")}</p></div></div><div class="legend" id="b1-legend"></div><div class="chart" id="b1"></div></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>${L("Drops follow the overload model 1 − 1/ρ", "Drop 符合過載模型 1 − 1/ρ")}</h3><p class="fig-sub">${L("Every baseline run · measured drop rate vs prediction from offered rate × service time", "每個 baseline run · 實測 drop rate vs 由 offered rate × service time 推得的預測值")}</p></div></div><div class="legend" id="b2-legend"></div><div class="chart" id="b2"></div></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>${L("Under overload, queue depth sets the latency", "過載時，queue depth 決定 latency")}</h3><p class="fig-sub">${L("P50 end-to-end latency at 20 FPS by KEEP_LAST depth · bar = mean, tick = P99 · 3 runs each", "20 FPS 下各 KEEP_LAST depth 的 P50 end-to-end latency · 長條 = 平均，刻線 = P99 · 各 3 runs")}</p></div></div><div class="chart" id="b3"></div>
        <p class="fig-note">${L("The single-threaded detector always serves the oldest of the <i>depth</i> frames DDS keeps, so queue wait ≈ depth / input rate once the detector is saturated.", "單執行緒的 detector 永遠處理 DDS 保留的 <i>depth</i> 個 frame 中最舊的那個，所以 detector 飽和後，queue wait ≈ depth / input rate。")}</p></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>${L("Injected service delay pushes both models into overload", "注入 service delay 讓兩個模型都進入過載")}</h3><p class="fig-sub">${L("Effective miss vs artificial delay added to each inference · 20 FPS, depth 5", "Effective miss vs 每次 inference 額外加入的 artificial delay · 20 FPS，depth 5")}</p></div></div><div class="legend" id="b4-legend"></div><div class="chart" id="b4"></div></div>
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
        series: models.map((m) => ({ name: MODEL[m].replace("MobileViT-", ""), color: MODEL_COLOR[m],
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
        series: models.map((m) => ({ name: MODEL[m].replace("MobileViT-", ""), color: MODEL_COLOR[m],
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

  /* =============================== SCHEDULING =============================== */
  function renderScheduling(sec) {
    sec.innerHTML = `
      <div class="view-head"><h2>${L("Six frame-scheduling policies, compared within blocks", "六種 frame scheduling policy，在 block 內比較")}</h2>
      <p>${L("Each block runs all six arms once, in rotated order, under identical controls. The run is the statistical unit and every comparison is a within-block paired difference. Deadline-Guard and Adaptive are always shown side by side.",
        "每個 block 在相同控制條件下，以輪替順序把六個 arms 各跑一次。統計單位是 run，所有比較都是 block 內的 paired difference。Deadline-Guard 與 Adaptive 一律並排呈現。")}</p></div>
      <div class="controls" id="s-controls"></div>
      <p class="context" id="s-context"></p>
      <div class="grid">
        <div class="span-7 panel"><div class="fig-head"><div class="titles"><h3 id="s1-title"></h3><p class="fig-sub" id="s1-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>${L("one run", "單一 run")}</span><span class="k"><span class="sw tick"></span>${L("mean", "平均")}</span><span class="k"><span class="sw line" style="background:var(--axis)"></span>min–max</span></div>
          <div class="chart" id="s1"></div>
          <p class="fig-note">${L("Latest-Frame, Deadline-Guard and Adaptive share the same queue, worker and controls, so this axis fits their range. FIFO and the legacy arms are on the full-scale chart below.",
            "Latest-Frame、Deadline-Guard 與 Adaptive 共用相同的 queue、worker 與控制條件，所以這張圖的座標軸只涵蓋它們的範圍。FIFO 與 legacy arms 請看下方完整刻度的圖。")}</p></div>
        <div class="span-5 panel"><div class="fig-head"><div class="titles"><h3>${L("Block by block", "逐 block 比較")}</h3><p class="fig-sub" id="s2-sub"></p></div></div><div class="chart" id="s2"></div>
          <p class="fig-note">${L("Each grey line is one experimental block. Running the arms back to back within a block reduces host-state variation between them; it does not make the host state identical.",
            "每條灰線是一個實驗 block。在同一個 block 內連續執行各 arm，可以減少它們之間的主機狀態差異，但無法讓主機狀態完全相同。")}</p></div>
      </div>
      <div class="grid section-gap">
        <div class="span-7 panel"><div class="fig-head"><div class="titles"><h3>${L("Paired differences: policy effect", "Paired differences：policy 效果")}</h3><p class="fig-sub" id="s3-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw dot" style="background:var(--ink-3)"></span>${L("mean of block differences", "block 差異的平均")}</span><span class="k"><span class="sw line" style="background:var(--ink)"></span>95% t-interval</span><span class="k"><span class="sw ring"></span>${L("one block", "單一 block")}</span></div>
          <div class="chart" id="s3"></div>
          <p class="fig-note" id="s3-note"></p></div>
        <div class="span-5 panel"><div class="fig-head"><div class="titles"><h3>${L("Against legacy depth 1", "與 legacy depth 1 比較")}</h3><p class="fig-sub">${L("Includes the architecture difference (DDS callback vs queue + worker), so it is not attributable to a policy", "包含 architecture 差異（DDS callback vs queue + worker），所以不能歸因於 policy")}</p></div></div><div class="chart" id="s4"></div>
          <p class="fig-note">${L("Legacy depth 1 varies strongly between runs (its service time is less stable), which is why these intervals are wide.", "Legacy depth 1 在不同 run 之間變動很大（service time 較不穩定），所以這些區間很寬。")}</p></div>
      </div>
      <div class="panel section-gap"><div class="fig-head"><div class="titles"><h3 id="s5-title"></h3><p class="fig-sub" id="s5-sub"></p></div></div>
        <div class="chart" id="s5"></div>
        <p class="fig-note">${L("The shaded range is where the three same-architecture arms fall. Legacy arms use a different execution path, so their gap to the application arms is not a policy effect.",
          "陰影範圍是三個相同 architecture arms 的分布範圍。Legacy arms 使用不同的執行路徑，所以它們與 application arms 的差距不是 policy 效果。")}</p></div>
      <div class="section-gap" id="s-table"></div>
      <details class="table-toggle"><summary>${L("Arm definitions", "Arm 定義")}</summary>${table([{ label: "Arm", l: true }, { label: L("Path", "路徑"), l: true }, { label: L("Behaviour", "行為"), l: true, wrap: true }],
        D.arms.map((a) => ({ cells: [sw(ARM[a.id].color) + esc(a.label), a.family === "legacy" ? L("Legacy (DDS callback)", "Legacy（DDS callback）") : L("Application queue + 1 worker", "Application queue + 1 個 worker"), esc(T(a, "summary"))] })))}</details>`;

    const ctl = sec.querySelector("#s-controls");
    control(ctl, "Condition", seg("Condition", condOptions(), state.c, (v) => { state.c = v; sync(); draw(); }));
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
      sec.querySelector("#s-context").innerHTML = `<b>${esc(c.label)}</b>${c.primary ? `<span class="pill">primary condition</span>` : ""} — ` + L(
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
        yTitle: M.label + (M.unit === "%" ? " (%)" : ` (${M.unit.trim()})`), zero: state.m !== "p99_latency_ms", ariaLabel: L("Per-block slope chart", "逐 block slope chart"),
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
        `↓ / ↑ count blocks where the first arm was lower / higher. With n = ${c.n_blocks} blocks the smallest possible exact sign-flip p is ${floor}, so these counts are a consistency check, not a significance test. FIFO − Latest-Frame is off this scale: ${fmt(fe.mean, M.dnd, true)}${M.d} ${ci(fe, M.dnd)}.`,
        `↓ / ↑ 表示第一個 arm 較低 / 較高的 block 數。n = ${c.n_blocks} blocks 時，exact sign-flip p 最小只能到 ${floor}，所以這些計數只是一致性檢查，不是顯著性檢定。FIFO − Latest-Frame 超出此刻度：${fmt(fe.mean, M.dnd, true)}${M.d} ${ci(fe, M.dnd)}。`);

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

  /* =============================== MECHANISM =============================== */
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
          <span class="cg-age" style="width:${pct(f.age)}"></span><span class="cg-svc" style="width:${pct(svc)}"></span>
          <span class="cg-dl" style="left:${pct(deadline)}"></span>
        </div>
        <div class="cg-out"><span class="cg-sum">${tot} ms ${ok ? "≤" : ">"} ${dl} ms</span><span class="cg-verdict ${ok ? "ok" : "no"}">${ok ? L("Serve", "處理") : L("Drop", "丟棄")}</span><span class="cg-note">${f.note}</span></div>
      </div>`; }).join("");
    return `<div class="panel concept"><div class="fig-head"><div class="titles"><h3>${L("How Deadline-Guard decides", "Deadline-Guard 如何做決定")}</h3>
        <p class="fig-sub">${L("When the worker is free, each queued frame's latency is predicted as <b>frame age</b> (now − publish time) + <b>estimated service time</b> (a quantile of recently measured service times). The guard serves the newest frame whose prediction fits the deadline.",
          "Worker 空閒時，每個排隊中 frame 的 latency 預測為 <b>frame age</b>（現在 − publish 時間）+ <b>估計 service time</b>（最近實測 service time 的分位數）。Guard 會處理預測值落在 deadline 內的最新 frame。")}</p></div>
        <span class="tag">${L("Concept illustration", "概念示意")}</span></div>
      <div class="legend"><span class="k"><span class="sw cg-sw-age"></span>frame age</span><span class="k"><span class="sw cg-sw-svc"></span>${L("estimated service time", "估計 service time")}</span><span class="k"><span class="sw dash"></span>deadline ${dl} ms</span></div>
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
      <div class="panel section-gap"><div class="fig-head"><div class="titles"><h3>${L("Worst-case age of the newest frame vs the deadline", "最新 frame 的最壞情況 age vs deadline")}</h3><p class="fig-sub">${L("inter-arrival interval (1000 / FPS) + measured Latest-Frame service time, per fixed-rate condition", "各固定速率 condition 的 inter-arrival 間隔（1000 / FPS）+ 實測 Latest-Frame service time")}</p></div><span class="tag measured">${L("Measured", "實測")}</span></div>
        <div class="legend"><span class="k"><span class="sw" style="background:var(--axis)"></span>inter-arrival (1000 / FPS)</span><span class="k"><span class="sw" style="background:var(--ink-2)"></span>${L("service time (Latest-Frame, measured)", "service time（Latest-Frame，實測）")}</span><span class="k"><span class="sw dash"></span>deadline</span></div>
        <div class="chart" id="m1"></div><div id="m1-table" style="margin-top:14px"></div>
        <p class="fig-note">${esc(T(Mx, "model_note"))}</p></div>
      <div class="controls" id="m-controls" style="margin-top:var(--sp-7)"></div>
      <div class="grid">
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>${L("What the effective miss is made of", "Effective miss 的組成")}</h3><p class="fig-sub" id="m2-sub"></p></div></div>
          <div class="legend"><span class="k"><span class="sw" style="background:var(--s7)"></span>${L("dropped (never processed)", "dropped（從未處理）")}</span><span class="k"><span class="sw" style="background:var(--s8)"></span>${L("late (processed after the deadline)", "late（超過 deadline 才處理完）")}</span></div><div class="chart" id="m2"></div>
          <p class="fig-note">${L("Guard trades a few more drops for almost no late frames. Shares are of all published frames.", "Guard 多丟一些 frame，換來幾乎沒有 late frame。比例以所有 published frames 為分母。")}</p></div>
        <div class="span-6 panel"><div class="fig-head"><div class="titles"><h3>${L("Queueing: frame age when inference starts", "Queueing：inference 開始時的 frame age")}</h3><p class="fig-sub" id="m3-sub"></p></div></div><div class="chart" id="m3"></div>
          <p class="fig-note">${L("Queues that serve the oldest frame (FIFO, legacy depth 5) make every frame wait for the whole backlog under overload.", "處理最舊 frame 的 queue（FIFO、legacy depth 5）在過載時會讓每個 frame 都等完整個 backlog。")}</p></div>
      </div>
      <div class="panel section-gap"><div class="fig-head"><div class="titles"><h3>${L("Ablation: Adaptive − Deadline-Guard", "Ablation：Adaptive − Deadline-Guard")}</h3><p class="fig-sub">${L("Δ effective miss (pp), within-block, every condition and each phase of the dynamic run · Adaptive = Guard + utilisation switch", "Δ effective miss (pp)，block 內比較，涵蓋每個 condition 及 dynamic run 的每個 phase · Adaptive = Guard + utilisation switch")}</p></div></div>
        <div class="chart" id="m4"></div><div id="m4-table" style="margin-top:14px"></div>
        <p class="fig-note">${L("The switch can only change a decision when ≥ 2 feasible frames are queued and estimated ρ &lt; 1. In these conditions the queue rarely holds two feasible frames, so EDF and newest-feasible pick the same frame.",
          "只有在 queue 中有 ≥ 2 個 feasible frames 且估計 ρ &lt; 1 時，switch 才可能改變決定。在這些 conditions 下 queue 很少同時有兩個 feasible frames，所以 EDF 與 newest-feasible 會選到同一個 frame。")}</p></div>
      ${dyn.condition ? `<div class="panel section-gap"><div class="fig-head"><div class="titles"><h3>${L("Dynamic load", "動態負載")}: ${esc(COND[dyn.condition].label)}</h3><p class="fig-sub">${L(`Effective miss per phase (20 s each) · mean and min–max over ${COND[dyn.condition].n_blocks} runs per arm`, `各 phase（各 20 秒）的 effective miss · 每個 arm ${COND[dyn.condition].n_blocks} runs 的平均與 min–max`)}</p></div></div>
        <div class="grid" id="m5"></div><div id="m5-table" style="margin-top:6px"></div></div>` : ""}`;

    // M1 feasibility
    C.hbars(sec.querySelector("#m1"), {
      rows: Mx.feasibility.map((f) => ({ label: COND[f.condition].label, dim: !f.overloaded, segments: [
        { v: f.inter_arrival_ms, color: "var(--axis)", name: "inter-arrival" }, { v: f.service_ms, color: "var(--ink-2)", name: "service" }],
        valueText: `${fmt(f.age_bound_ms, 0)} ms`, valueNote: f.overloaded ? "" : L("not overloaded, age ≈ 0", "未過載，age ≈ 0"),
        tip: tipRows(COND[f.condition].label, [["inter-arrival", fmt(f.inter_arrival_ms, 1) + " ms"], ["service (Latest)", fmt(f.service_ms, 1) + " ms"], [L("sum", "合計"), fmt(f.age_bound_ms, 1) + " ms"], ["ρ", fmt(f.utilization, 2)], [L("overloaded", "過載"), f.overloaded ? L("yes", "是") : L("no", "否")]]) })),
      refs: [{ value: Mx.feasibility[0].deadline_ms, label: `deadline ${fmt(Mx.feasibility[0].deadline_ms, 0)} ms` }], xTitle: L("Milliseconds", "毫秒"), rowH: 36, ariaLabel: L("Inter-arrival plus service time versus deadline", "Inter-arrival + service time vs deadline"),
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
            segments: [{ v: drop, color: "var(--s7)", name: "dropped" }, { v: late, color: "var(--s8)", name: "late" }],
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

  /* =============================== EVIDENCE =============================== */
  function renderEvidence(sec) {
    const B = D.baseline, K = D.kpis;
    const ok = '<svg class="ic ok" viewBox="0 0 18 18" aria-label="ok"><circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 9.2l2.3 2.3 4.7-4.9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const allSame = (ctrls) => ctrls.every((x) => x.identical);
    const p3all = S.runs.length;
    const ctrlMap = {}; B.controls.forEach((x) => { ctrlMap[x.label] = { p2: x }; }); S.controls.forEach((x) => { (ctrlMap[x.label] = ctrlMap[x.label] || {}).p3 = x; });
    const showVal = (x) => !x ? "—" : x.values.map((v) => esc(Array.isArray(v) ? v.join(",") : typeof v === "number" && v >= 1 << 30 ? `${v} (${(v / (1 << 30)).toFixed(0)} GiB)` : /^[0-9a-f]{40,}$/.test(String(v)) ? String(v).slice(0, 12) + "…" : v)).join(" / ") + (x.identical ? "" : ` <span class="muted">${L("(differs)", "（不一致）")}</span>`);
    const p3Same = allSame(S.controls), p2Same = allSame(B.controls);
    const minBlocks = Math.min(...S.conditions.map((c) => c.n_blocks));
    sec.innerHTML = `
      <div class="view-head"><h2>${L("Where every number comes from", "每個數字從哪裡來")}</h2>
      <p>${L("The dashboard bundle is generated by <code>python3 -m src.dashboard.build_data</code>. It refuses to write anything unless each table it reads matches its SHA-256 manifest down to the raw per-frame CSVs, every run is constrained and DDS-verified, and every block contains all six arms.",
        "Dashboard 的資料 bundle 由 <code>python3 -m src.dashboard.build_data</code> 產生。除非讀取的每張表都能透過 SHA-256 manifest 一路對回原始 per-frame CSV、每個 run 都是 constrained 且 DDS 已驗證、每個 block 都包含全部六個 arms，否則它不會寫出任何檔案。")}</p></div>
      <div class="grid">
        <div class="span-6 panel"><h3>${L("Checks passed when this bundle was built", "建置此 bundle 時通過的檢查")}</h3>
          <ul class="status-list" style="margin-top:8px">
            <li>${ok}<div><div class="t">${L("Phase 2 baseline chain", "Phase 2 baseline 鏈")}</div><div class="x">${L(`${B.chain_records_verified} file records hash-verified (raw runs → runtime summary → baseline aggregates). ${B.n_runs} runs, all <code>constrained</code>, all DDS SHM-verified.`,
              `${B.chain_records_verified} 筆檔案紀錄 hash 已驗證（raw runs → runtime summary → baseline aggregates）。${B.n_runs} 個 runs，全部 <code>constrained</code>，全部 DDS SHM 已驗證。`)}</div></div></li>
            <li>${ok}<div><div class="t">${L("Phase 3 formal A/B chain", "Phase 3 正式 A/B 鏈")}</div><div class="x">${L(`${S.chain_records_verified} file records hash-verified (raw runs → formal summary → per-arm, paired and dynamic-phase tables). ${p3all} runs in ${S.n_blocks} complete blocks.`,
              `${S.chain_records_verified} 筆檔案紀錄 hash 已驗證（raw runs → formal summary → per-arm、paired 與 dynamic-phase 表格）。${S.n_blocks} 個完整 blocks 共 ${p3all} 個 runs。`)}</div></div></li>
            <li>${ok}<div><div class="t">${L("Measured code is the committed code", "量測用的程式碼就是已 commit 的程式碼")}</div><div class="x">Phase 3: ${S.commits.map((c) => `${c.runs} runs at <code>${c.commit}</code>, dirty=${c.dirty}`).join("; ")}. Phase 2: ${B.commits.map((c) => `${c.runs} at <code>${c.commit}</code>, dirty=${c.dirty}`).join("; ")}.</div></div></li>
            <li>${ok}<div><div class="t">${L("Controls identical across runs", "各 run 的控制條件一致")}</div><div class="x">${L(`${p3Same ? "All" : "Not all"} ${S.controls.length} Phase 3 and ${p2Same ? "all" : "not all"} ${B.controls.length} Phase 2 recorded controls hold a single value (table below).`,
              `Phase 3 的 ${S.controls.length} 項${p3Same ? "全部" : "並非全部"}、Phase 2 的 ${B.controls.length} 項${p2Same ? "全部" : "並非全部"}記錄控制條件都只有單一數值（見下表）。`)}</div></div></li>
            <li>${ok}<div><div class="t">${L("Excluded data cannot leak in", "排除的資料不會混入")}</div><div class="x">${L("Paths containing <code>pilot</code>, <code>legacy_unverified</code>, <code>example</code> or <code>runtime_aware</code>, and run ids outside the formal run tags, stop the build (tested).",
              "路徑含 <code>pilot</code>、<code>legacy_unverified</code>、<code>example</code> 或 <code>runtime_aware</code>，或 run id 不屬於正式 run tag，都會讓建置中止（已有測試）。")}</div></div></li>
          </ul>
          <p class="fig-note">${L("Independent gates (also in CI):", "獨立的 gate（CI 也會執行）：")} <code>python3 scripts/check_runtime_provenance.py</code> (Phase 2) ${L("and", "與")} <code>python3 scripts/check_phase3_provenance.py</code> (Phase 3) ${L("must both report VERIFIED.", "都必須回報 VERIFIED。")}</p></div>
        <div class="span-6 panel"><h3>${L("Run inventory", "Run 清單")}</h3>
          ${table([{ label: L("Dataset", "資料集"), l: true }, { label: "Runs" }, { label: L("Design", "設計"), l: true }],
            [{ cells: ["Phase 2 / Batch 2 baseline", B.n_runs, L(`${B.n_conditions} conditions × 3 runs · 60 s`, `${B.n_conditions} conditions × 3 runs · 60 秒`)] },
             ...S.conditions.map((c) => ({ hl: c.primary, cells: [`Phase 3 · ${esc(c.label)}${c.primary ? " (primary)" : ""}`, c.n_runs, L(`${c.n_blocks} blocks × 6 arms · 65 s`, `${c.n_blocks} blocks × 6 arms · 65 秒`)] })),
             { cells: [`<b>${L("Total", "合計")}</b>`, `<b>${K.runs.total}</b>`, ""] }])}
          <p class="fig-note">${L("Phase 2 groups:", "Phase 2 分組：")} ${Object.entries(B.run_groups).map(([k, v]) => `${esc(k)} ${v}`).join(", ")}. ${L("Warm-up: first 10 processed frames of every run excluded.", "Warm-up：每個 run 前 10 個 processed frames 不列入統計。")}</p></div>
      </div>
      <div class="panel section-gap"><h3>${L("Controlled variables", "控制變因")}</h3><p class="fig-sub">${L("Read from every run's <code>meta.json</code>; ✓ = one value across all runs of that phase.", "讀自每個 run 的 <code>meta.json</code>；✓ = 該 phase 所有 runs 都是同一個值。")}</p>
        <div style="margin-top:12px">${table([{ label: L("Control", "控制項"), l: true }, { label: "Phase 2 baseline", l: true }, { label: "", l: false }, { label: "Phase 3 formal", l: true }, { label: "" }],
          Object.entries(ctrlMap).map(([k, v]) => ({ cells: [esc(k), showVal(v.p2), v.p2 ? (v.p2.identical ? '<span class="check">✓</span>' : "✗") : "", showVal(v.p3), v.p3 ? (v.p3.identical ? '<span class="check">✓</span>' : "✗") : ""] })))}</div>
        <p class="fig-note">${L("Also fixed: COCO128 images cycled by the publisher, publisher RELIABLE depth 10 → detector BEST_EFFORT KEEP_LAST, application arms DDS depth 10 and queue capacity 5, host load gate before every Phase 3 block.",
          "以下也固定不變：publisher 循環送出 COCO128 影像、publisher RELIABLE depth 10 → detector BEST_EFFORT KEEP_LAST、application arms 的 DDS depth 10 與 queue capacity 5，以及每個 Phase 3 block 之前的 host load gate。")}</p></div>
      <div class="grid section-gap">
        <div class="span-6 panel"><h3>${L("Statistical method", "統計方法")}</h3>
          <ul class="limits small" style="margin-top:8px">
            <li>${L("<b>Unit of analysis is the run.</b> Frames are never pooled into one large sample; ± is the SD across runs.", "<b>分析單位是 run。</b>不會把所有 frame 合併成一個大樣本；± 是各 run 之間的 SD。")}</li>
            <li>${L("<b>Paired within blocks.</b> Every Phase 3 block runs all six arms once in rotated order; differences are taken inside a block, then averaged.", "<b>Block 內配對。</b>每個 Phase 3 block 以輪替順序把六個 arms 各跑一次；先在 block 內取差異，再取平均。")}</li>
            <li>${L("<b>95% Student-t interval</b> on the block differences, plus the number of blocks with a negative / positive difference and the exact two-sided sign-flip p.", "對 block 差異計算 <b>95% Student-t interval</b>，並附上差異為負 / 正的 block 數，以及 exact two-sided sign-flip p。")}</li>
            <li>${L("<b>No significance claims.</b> With 5 blocks the smallest sign-flip p is 0.0625 (3 blocks: 0.25). Results are reported as effect size, interval and consistency.", "<b>不宣稱顯著性。</b>5 個 blocks 時 sign-flip p 最小為 0.0625（3 個 blocks：0.25）。結果以 effect size、區間與一致性呈現。")}</li>
            <li>${L("<b>Causal comparisons only inside one architecture</b> (Guard / Adaptive / Latest / FIFO). Differences to the legacy path also contain an architecture effect.", "<b>因果比較只在同一個 architecture 內進行</b>（Guard / Adaptive / Latest / FIFO）。與 legacy 路徑的差異同時包含 architecture 效果。")}</li>
            <li>${L("<b>Pre-specified analysis plan.</b> The primary condition, metrics and comparisons were fixed in the project before the formal runs (an internal plan, not an external preregistration); Adaptive parameters were not tuned on the pilot.", "<b>預先指定的分析計畫。</b>Primary condition、指標與比較方式在正式 run 之前就已在專案中固定（內部計畫，非外部 preregistration）；Adaptive 參數沒有用 pilot 調整。")}</li>
          </ul></div>
        <div class="span-6 panel"><h3>${L("Known limitations", "已知限制")}</h3>
          <ul class="limits small" style="margin-top:8px">
            <li>${L("<b>One host, one session per phase.</b> i7-13700, two P-cores (12, 14), <code>powersave</code> governor, shared machine (load gate + nice 10). Results do not establish behaviour on other hardware.", "<b>單一主機，每個 phase 一個 session。</b>i7-13700、兩顆 P-core（12、14）、<code>powersave</code> governor、共用機器（load gate + nice 10）。結果不能推論到其他硬體。")}</li>
            <li>${L(`<b>Small samples.</b> ${COND[D.primary_condition].n_blocks} blocks for the primary condition, ${minBlocks} for the others.`, `<b>樣本小。</b>Primary condition ${COND[D.primary_condition].n_blocks} 個 blocks，其他 ${minBlocks} 個。`)}</li>
            <li>${L("<b>“No difference” is not equivalence.</b> Adaptive − Guard intervals exclude effects larger than about 1–2 pp; no formal equivalence test was run.", "<b>「沒有差異」不等於「等價」。</b>Adaptive − Guard 的區間排除了大於約 1–2 pp 的效果，但沒有做正式的 equivalence test。")}</li>
            <li>${L("<b>One parameter set.</b> 100 ms deadline, queue capacity 5, one Adaptive configuration, one step pattern for dynamic load. The utilisation switch might matter with ρ≈1 and longer queues, deadlines far above service time, or high service-time variance — untested.", "<b>只有一組參數。</b>100 ms deadline、queue capacity 5、一種 Adaptive 設定、一種動態負載階躍模式。在 ρ≈1 且 queue 較長、deadline 遠大於 service time，或 service time 變異很大時，utilisation switch 可能會有作用——尚未測試。")}</li>
            <li>${L("<b>Architecture effects.</b> MobileViT-XXS application arms are ~1.2 ms slower per frame than legacy; legacy service time varies more between runs, cause not measured.", "<b>Architecture 效果。</b>MobileViT-XXS 的 application arms 每個 frame 比 legacy 慢約 1.2 ms；legacy 的 service time 在不同 run 之間變動較大，原因未量測。")}</li>
            <li>${L("<b>Latency only.</b> Random-initialised weights; no accuracy. No energy was measured; EDA-Lite energy is a simulation estimate.", "<b>只量 latency。</b>使用 random-initialised weights，沒有 accuracy。沒有量測 energy；EDA-Lite 的 energy 是模擬估計值。")}</li>
          </ul></div>
      </div>
      <div class="grid section-gap">
        <div class="span-6 panel"><h3>${L("Excluded from every KPI", "不列入任何 KPI 的資料")}</h3>
          ${table([{ label: L("Data", "資料"), l: true, wrap: true }, { label: L("Why", "原因"), l: true, wrap: true }], D.excluded.map((e) => ({ cells: [`<code>${esc(e.path)}</code>`, esc(T(e, "reason"))] })))}</div>
        <div class="span-6 panel"><h3>${L("Reproduce", "重現步驟")}</h3>
          <pre class="cmd">${L("# verify the measured data (exit 0 = VERIFIED)", "# 驗證實測資料（exit 0 = VERIFIED）")}
python3 scripts/check_runtime_provenance.py
python3 scripts/check_phase3_provenance.py --expect-runs ${S.n_runs}

${L("# rebuild this dashboard's data from the tables", "# 從表格重建這個 dashboard 的資料")}
python3 -m src.dashboard.build_data
python3 -m src.dashboard.build_data --check   # 0 = current

${L("# preview on the server (localhost only; VS Code forwards it)", "# 在伺服器上預覽（只限 localhost；VS Code 會自動轉發）")}
bash scripts/serve_dashboard.sh</pre>
          <p class="fig-note">${L("Rebuilding the tables themselves from raw runs: see README → Reproducibility.", "要從 raw runs 重建表格本身，請見 README → Reproducibility。")}</p></div>
      </div>
      <details class="table-toggle section-gap"><summary>${L(`All ${D.sources.length} source files with SHA-256`, `全部 ${D.sources.length} 個來源檔與 SHA-256`)}</summary>
        ${table([{ label: L("Path", "路徑"), l: true }, { label: L("Role", "用途"), l: true }, { label: "SHA-256", l: true }], D.sources.map((s) => ({ cells: [`<code>${esc(s.path)}</code>`, esc(T(s, "role")), `<code>${s.sha256.slice(0, 16)}…</code>`] })))}</details>`;
  }

  const RENDER = { overview: renderOverview, baseline: renderBaseline, scheduling: renderScheduling, mechanism: renderMechanism, evidence: renderEvidence };
  route();
})();
