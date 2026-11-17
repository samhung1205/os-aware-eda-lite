/* Overview view: the question, the regime figure, the system and the findings. Numbers come from window.DASHBOARD_DATA through window.Dash (assets/app.js).
 * Text is written as L(english, traditional_chinese); see assets/i18n.js. */
(function () {
  "use strict";
  const X = window.Dash;
  if (!X) return;
  const { D, C, L, T, fmt, esc, S, ARM, COND, MODEL, MODEL_COLOR, APP_ORDER, LEGACY_ORDER, METRICS, betterText,
    armRow, pairRow, runsOf, blockNo, ci, tipRows, sw, blockDiffs, state, setParams, seg, control, table, spec, condOptions } = X;

  function renderOverview(sec) {
    const K = D.kpis;
    const g = K.guard_vs_latest_primary, ag = K.adaptive_vs_guard_primary;
    const pc = COND[D.primary_condition];
    const cap = K.capacity;
    const F = {}; D.findings.forEach((f) => { F[f.id] = f; });
    const chain = (D.baseline.chain_records_verified || 0) + (S.chain_records_verified || 0);
    const lat = armRow(pc.id, "latest_q10"), grd = armRow(pc.id, "guard_c5_q10"), ada = armRow(pc.id, "adaptive_c5_q10");
    const dl = fmt(pc.deadline_ms, 0);
    const archSvg = L("assets/architecture.svg", "assets/architecture_zh.svg");
    const FE = D.mechanism.feasibility;
    const fp = FE.find((f) => f.condition === pc.id) || FE[0];
    const GUARD = ARM.guard_c5_q10.color;
    const others = S.conditions.filter((c) => c.id !== pc.id).map((c) => c.n_blocks);
    const nOther = Math.min(...others) === Math.max(...others) ? others[0] : `${Math.min(...others)}–${Math.max(...others)}`;
    const arrow = X.ICON.arrow;
    const cmpMax = Math.ceil(Math.max(lat.effective_miss_rate_pct.mean, grd.effective_miss_rate_pct.mean, ada.effective_miss_rate_pct.mean) / 10) * 10;
    const cmpRow = (id, r) => `<div class="cmp-row"><span class="cmp-name">${sw(ARM[id].color)}${esc(ARM[id].label)}</span>` +
      `<span class="cmp-bar"><i style="width:${(100 * r.effective_miss_rate_pct.mean / cmpMax).toFixed(2)}%;background:${ARM[id].color}"></i></span>` +
      `<span class="cmp-v">${fmt(r.effective_miss_rate_pct.mean, 1)}%</span></div>`;
    sec.innerHTML = `
      <div class="hero">
        <div class="hero-main">
          <h2>${L("Which frames should an overloaded edge detector skip?", '過載的<span class="nowrap">邊緣偵測器</span><span class="nowrap">該跳過哪些 frame？</span>')}</h2>
        </div>
        <div class="hero-copy">
          <p class="answer-lead">${L(`The ones that can no longer make the deadline. That only happens when waiting plus service time can pass ${dl} ms.`, `跳過那些已經趕不上 deadline 的 frame。只有在「等待 + service time」可能超過 ${dl} ms 時才會發生。`)}</p>
          <p class="lede">${L("A ROS 2 benchmark of frame scheduling for a MobileViT detector on two pinned CPU cores with a 4 GiB memory limit; every run's constraints and shared-memory transport are read back and verified.",
            "在 2 顆綁定的 CPU core、4 GiB 記憶體上限下，實測 MobileViT 偵測器 frame scheduling 的 ROS 2 benchmark；每個 run 的限制條件與 shared-memory transport 都會讀回驗證。")}</p>
          <div class="links"><a href="#scheduling">${L("Compare policies", "比較各 policy")}${arrow}</a><a href="#mechanism">${L("Why it works", "為什麼有效")}${arrow}</a><a href="#evidence">${L("How it is verified", "如何驗證")}${arrow}</a></div>
        </div>
      </div>
      <div class="plate">
        <div class="plate-inner">
          <div class="fig-head">
            <div class="titles"><h3>${L("Where dropping late frames pays off", "丟棄趕不上的 frame 何時有用")}</h3></div>
            <p class="key-terms head-key">${L("<b>Δ effective miss</b> change in the share of published frames dropped or finished late · <b>pp</b> percentage points · <b>ρ</b> arrival rate × service time, overloaded above 1 · <b>S / XXS</b> MobileViT-S / -XXS · <b>+ 25 ms</b> injected service delay",
              "<b>Δ effective miss</b> 已發佈 frame 中被丟棄或遲到比例的變化 · <b>pp</b> 百分點 · <b>ρ</b> 抵達速率 × service time，大於 1 即過載 · <b>S / XXS</b> MobileViT-S / -XXS · <b>+ 25 ms</b> 注入的 service delay")}</p>
            ${X.MEAS}</div>
          <div class="chart" id="hero-regime"></div>
          <div class="plate-key">
            <div class="legend">
              <span class="k"><span class="sw open"></span>${L("waiting (overloaded only)", "等待（僅過載時）")}</span>
              <span class="k"><span class="sw solid"></span>${L("service time", "service time")}</span>
              <span class="k"><span class="sw overshoot-sw"></span>${L("past the deadline", "超過 deadline")}</span>
              <span class="k"><span class="sw ring" style="border-color:${GUARD}"></span>${L("one block", "單一 block")}</span>
              <span class="k"><span class="sw dot" style="background:${GUARD}"></span>${L("mean Δ with 95% interval", "平均 Δ 與 95% 區間")}</span>
            </div>
            <p class="key-terms">${L("<b>block</b> one round that runs every arm once; differences are paired within it", "<b>block</b> 每個 arm 各跑一次的一輪，差異在 block 內配對")}</p>
          </div>
          <div class="plate-foot">
            <div>
              <p class="answer">${L(`Of the ${FE.length} fixed-rate conditions tested, only at <b>${esc(pc.label)}</b> can the newest frame be too old to finish within ${dl} ms: up to ${fmt(fp.inter_arrival_ms, 0)} ms of waiting plus ${fmt(fp.service_ms, 0)} ms of service reaches ${fmt(fp.age_bound_ms, 0)} ms. Everywhere else the interval includes zero, and <b>Adaptive</b>, which adds a utilisation switch, lands where Deadline-Guard does.`,
                `在測試的 ${FE.length} 個固定速率 condition 中，只有 <b>${esc(pc.label)}</b> 下最新的 frame 可能已經太舊、無法在 ${dl} ms 內完成：最多 ${fmt(fp.inter_arrival_ms, 0)} ms 的等待加上 ${fmt(fp.service_ms, 0)} ms 的 service，達到 ${fmt(fp.age_bound_ms, 0)} ms。其他 condition 的區間都包含 0；再加上 utilisation switch 的 <b>Adaptive</b>，結果與 Deadline-Guard 相同。`)}</p>
              <p class="fig-note">${L(`Each lane: the newest frame's worst case against the ${dl} ms deadline. Right: Deadline-Guard − Latest-Frame effective miss, paired within blocks. One host, ${pc.n_blocks} blocks at the primary condition and ${nOther} at the others, latency only (random-initialised weights); ${K.runs.total} constrained runs in all, ${chain} file hashes verified. An interval that includes 0 is not an equivalence test. <a href="#evidence/limitations">Limitations</a>`,
                `每條 lane：最新 frame 的最壞情況，對照 ${dl} ms deadline。右側：Deadline-Guard − Latest-Frame 的 effective miss，在 block 內配對比較。單一主機，primary condition ${pc.n_blocks} 個 blocks、其他 condition 各 ${nOther} 個，只量 latency（random-initialised weights）；共 ${K.runs.total} 個 constrained runs，已驗證 ${chain} 個檔案 hash。區間包含 0 不代表兩者等價。<a href="#evidence/limitations">使用限制</a>`)}</p>
              <details class="table-toggle glossary"><summary>${L("All terms on this page", "本頁所有術語")}</summary>
                <dl>
                  <dt>Effective miss</dt><dd>${L(`Share of published frames that were dropped or finished after the ${dl} ms deadline. Lower is better.`, `已發佈的 frame 中，被丟棄或超過 ${dl} ms deadline 才完成的比例，越低越好。`)}</dd>
                  <dt>pp</dt><dd>${L("Percentage points: the gap between two percentages. 20% → 15% is −5 pp.", "百分點：兩個百分比之間的差。20% → 15% 是 −5 pp。")}</dd>
                  <dt>ρ</dt><dd>${L("Utilisation, arrival rate × service time. Above 1 the detector cannot keep up and must skip frames.", "使用率，即抵達速率 × service time。大於 1 表示偵測器跟不上，必須跳過 frame。")}</dd>
                  <dt>Arm</dt><dd>${L("One configuration under test: the four policies that share the application queue (FIFO, Latest-Frame, Deadline-Guard, Adaptive) and two legacy paths that run inference in the DDS callback.", "一個受測配置：共用 application queue 的四種 policy（FIFO、Latest-Frame、Deadline-Guard、Adaptive），以及在 DDS callback 內執行 inference 的兩條 legacy 路徑。")}</dd>
                  <dt>Block</dt><dd>${L("One round in which every arm runs once, back to back, in rotating order. Arms are compared within a block, so slow drift of the host cancels out.", "每個 arm 依輪替順序各跑一次的一輪。比較都在 block 內進行，主機狀態的緩慢漂移因此互相抵銷。")}</dd>
                  <dt>${L("Paired Δ, 95% CI", "Paired Δ、95% CI")}</dt><dd>${L("The mean of the per-block differences and its 95% t-interval. An interval that excludes 0 means the mean difference is distinguishable from 0 under the t-model; whether every block moved the same way is a separate count, shown as blocks lower / higher.", "各 block 差值的平均與其 95% t 區間。區間不包含 0，表示在 t 模型下平均差異可與 0 區分；每個 block 的方向是否一致是另一回事，由「較低 / 較高的 blocks」計數呈現。")}</dd>
                </dl></details>
            </div>
            <div class="result" role="group" aria-label="${L("Main result", "主要結果")}">
              <p class="cmp-cap">${L(`At ${esc(pc.label)}, the primary condition · ρ ≈ ${fmt(lat.utilization.mean, 2)} · effective miss, lower is better`,
                `${esc(pc.label)}（primary condition）· ρ ≈ ${fmt(lat.utilization.mean, 2)} · effective miss，越低越好`)}</p>
              <div class="cmp">${cmpRow("latest_q10", lat)}${cmpRow("guard_c5_q10", grd)}${cmpRow("adaptive_c5_q10", ada)}</div>
              <p class="r-diff">${L(`Guard − Latest, paired within blocks: 95% CI ${ci(g, 1)} pp, lower in ${g.n_neg} of ${g.n_blocks} blocks · Adaptive − Guard ${fmt(ag.mean, 1, true)} pp ${ci(ag, 1)}`,
                `Guard − Latest（block 內配對）：95% CI ${ci(g, 1)} pp，${g.n_blocks} 個 blocks 中有 ${g.n_neg} 個較低 · Adaptive − Guard ${fmt(ag.mean, 1, true)} pp ${ci(ag, 1)}`)}</p>
            </div>
          </div>
        </div>
      </div>

      <section class="section">
        <div class="section-head"><h3>${L("The system", "系統架構")}</h3>
          <p>${L("One detector, one worker, a bounded queue in front of it, and a policy that decides which frame runs next.", "一個 detector、一個 worker、前面一個 bounded queue，再加上一個決定下一個要處理哪個 frame 的 policy。")}</p></div>
        <div class="prose-cols">
          <div><h4>${L("Problem", "問題")}</h4><p>${L(`MobileViT-S saturates at about ${fmt(cap.mobilevit_s.mean, 0)} FPS on two cores. When frames arrive faster, some must be skipped. Always running the newest frame can still spend inference time on frames that then finish after the ${dl} ms deadline.`,
            `MobileViT-S 在兩顆 core 上約 ${fmt(cap.mobilevit_s.mean, 0)} FPS 就飽和。frame 進來得更快時，一定要跳過一部分。即使永遠處理最新的 frame，仍可能把 inference 時間花在最後超過 ${dl} ms deadline 才完成的 frame 上。`)}</p></div>
          <div><h4>${L("Approach", "做法")}</h4><p>${L("FIFO, Latest-Frame, Deadline-Guard and Adaptive share one application queue and one inference worker, so differences between them are policy effects. Deadline-Guard predicts, before inference, whether a frame can still meet its deadline; Adaptive adds a utilisation switch.",
            "FIFO、Latest-Frame、Deadline-Guard 與 Adaptive 共用同一個 application queue 與同一個 inference worker，所以它們之間的差異就是 policy 的效果。Deadline-Guard 在 inference 之前預測 frame 是否還趕得上 deadline；Adaptive 則再加上 utilisation switch。")}</p></div>
          <div><h4>${L("Evidence", "證據")}</h4><p>${L("Policies run interleaved in blocks under identical controls and are compared within each block. Every table on this site is rebuilt from raw per-frame logs and checked against SHA-256 manifests before the page is generated.",
            "各 policy 在相同控制條件下以 block 交錯執行，並在每個 block 內比較。網站上的每張表都從原始 per-frame log 重建，並在產生頁面前與 SHA-256 manifest 核對。")}</p></div>
        </div>
        <div class="fig arch-panel"><div class="arch-scroll">
          <img class="arch" src="${archSvg}" alt="${L("Architecture: image_stream_node publishes frames over Fast DDS shared memory to the MobileViT detector node. The legacy path runs inference in the DDS callback; the application path puts frames in a bounded queue served by one worker using FIFO, Latest-Frame, Deadline-Guard or Adaptive. Each run writes detector and publisher CSVs, metadata and a runtime probe; analysis tools build summaries and aggregates with SHA-256 manifests; provenance gates and the dashboard builder verify the chain. Separately, the EDA-Lite simulator turns simplified model profiles into cost-model estimates.",
            "架構圖：image_stream_node 透過 Fast DDS shared memory 把 frame 送到 MobileViT detector node。Legacy 路徑在 DDS callback 內執行 inference；application 路徑把 frame 放進 bounded queue，由一個 worker 依 FIFO、Latest-Frame、Deadline-Guard 或 Adaptive 處理。每個 run 會寫出 detector 與 publisher CSV、metadata 和 runtime probe；分析工具產生帶 SHA-256 manifest 的 summary 與 aggregate；provenance gate 與 dashboard builder 驗證整條鏈。另外，EDA-Lite simulator 把簡化的 model profile 轉成 cost-model 估計值。")}">
</div><p class="arch-open"><a href="${archSvg}" target="_blank" rel="noopener">${L("Open the full-size diagram", "開啟完整尺寸架構圖")}</a><span class="arch-hint">${L(" · or scroll sideways", " · 或左右捲動")}</span></p></div>
      </section>

      <section class="section">
        <div class="section-head"><h3>${L("Findings", "研究發現")}</h3>
          <p>${L("The policy result is the figure above. These answers are generated from the result tables when the dashboard is built.", "Policy 的結果就是上方的圖。以下回答都是在建置 dashboard 時從結果表格自動產生的。")}</p></div>
        <div class="grid">
          <div class="span-7">
            <ol class="qlist">
              <li><div class="q">${L("Where does the pipeline saturate, and why are frames lost?", "Pipeline 在哪裡飽和？frame 為什麼會遺失？")}</div><div class="a">${esc(T(F.capacity, "text"))}</div></li>
              <li><div class="q">${L("Does Adaptive's utilisation switch add anything beyond the deadline check?", "Adaptive 的 utilisation switch 在 deadline 檢查之外還有額外效益嗎？")}</div><div class="a">${esc(T(F.adaptive, "text"))}</div></li>
            </ol>
          </div>
          <div class="span-5">
            <ul class="findings">
              ${["dynamic"].filter((k) => F[k]).map((k) => `<li><div class="t">${esc(T(F[k], "title"))}</div><div class="x">${esc(T(F[k], "text"))}</div></li>`).join("")}
              <li><div class="t">${L("Legacy comparisons are kept separate", "Legacy 比較分開呈現")}</div><div class="x">${L(`The legacy arms run inference inside the DDS callback, so differences against them mix architecture and policy and are never attributed to a policy. <a href="#scheduling/paired">See paired differences</a>`,
                `Legacy arms 在 DDS callback 內執行 inference，所以與它們的差異混合了 architecture 與 policy 的效果，一律不歸因於 policy。<a href="#scheduling/paired">查看 paired differences</a>`)}</div></li>
            </ul>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="section-head"><h3>${L("What the project contributes", "專案貢獻")}</h3></div>
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

    C.regimeMap(sec.querySelector("#hero-regime"), {
      deadline: pc.deadline_ms, deadlineLabel: `deadline ${dl} ms`, unit: " pp", sweep: true,
      waitWord: L("wait", "等待"), serviceWord: L("service", "service"), dHead: L("Δ effective miss · Guard − Latest", "Δ effective miss · Guard − Latest"),
      betterLabel: L("← fewer misses with Guard", "← Guard 較少 miss"),
      tTitle: L("ms after publish", "發佈後的 ms"), dTitle: "Δ effective miss (pp)",
      ariaLabel: L("Per condition: the newest frame's worst-case finish time against the deadline, and Deadline-Guard minus Latest-Frame effective miss", "各 condition：最新 frame 的最壞完成時間對照 deadline，以及 Deadline-Guard − Latest-Frame 的 effective miss"),
      rows: FE.map((f) => {
        const e = f.guard_minus_latest_eff_pp, c = COND[f.condition];
        const age = f.overloaded ? f.inter_arrival_ms : 0;
        const none = armRow(f.condition, "latest_q10").effective_miss_rate_pct.mean === 0 && armRow(f.condition, "guard_c5_q10").effective_miss_rate_pct.mean === 0;
        return { label: c.label, trace: f.condition === pc.id, zeroNote: none ? L("no misses under either policy", "兩種 policy 都沒有 miss") : "", sub: `ρ ${fmt(f.utilization, 2)} · ${f.overloaded ? L("overloaded", "過載") : L("not overloaded", "未過載")}`,
          age, service: f.service_ms, mean: e.mean, lo: e.lo, hi: e.hi, color: GUARD, valueText: fmt(e.mean, 1, true),
          points: blockDiffs(f.condition, "guard_c5_q10", "latest_q10", "effective_miss_rate_pct", e, c.n_blocks, 2, " pp"),
          tip: tipRows(c.label, [["ρ", fmt(f.utilization, 2)],
            [L("waiting, worst case", "等待（最壞）"), f.overloaded ? fmt(f.inter_arrival_ms, 1) + " ms" : L("≈ 0 ms, not overloaded", "≈ 0 ms，未過載")],
            [L("service (Latest-Frame)", "service（Latest-Frame）"), fmt(f.service_ms, 1) + " ms"],
            [L("worst-case finish", "最壞完成時間"), `${fmt(age + f.service_ms, 1)} ms`],
            ["Guard − Latest", fmt(e.mean, 2, true) + " pp"], ["95% CI", ci(e, 2)],
            [L("blocks lower / higher", "blocks 較低 / 較高"), `${e.n_neg} / ${e.n_pos}`]]) };
      }) });
  }

  X.views.overview = renderOverview;
})();
