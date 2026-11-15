"use strict";

const STAGES = [
  {k: "environment", t: "Prepare environment", d: "Install the project's declared requirements (requirements*.txt, pyproject.toml) from prebuilt wheels. This is the only step with network access; everything after runs offline.", tags: ["sandbox", "evidence"]},
  {k: "discover", t: "Discover", d: "Collect the repository's pytest tests. Import errors are reported as an environment problem, not as flaky or broken tests.", tags: ["sandbox"]},
  {k: "stability", t: "Shuffled stability runs", d: "Run the whole suite many times in random order, recording every seed and outcome, to find tests that sometimes fail.", tags: ["sandbox", "evidence"]},
  {k: "investigate", t: "Classify and bisect", d: "Replay the failing order. If the test only fails after others, delta debugging shrinks the order to the exact polluter test.", tags: ["sandbox", "evidence"]},
  {k: "diagnose", t: "Diagnose", d: "The reasoner model sees the polluter, the victim, the code they import and a fresh failure, and returns a structured cause and patch.", tags: ["Nemotron reasoner"]},
  {k: "repair", t: "Verify the repair", d: "The patch is applied to a sandbox copy. It counts as verified only if the failing order passes and repeated shuffled runs stay green. Patches that weaken tests are rejected.", tags: ["sandbox", "evidence"]},
  {k: "characterize", t: "Characterize behavior", d: "The worker model proposes inputs; each function runs twice and only repeatable results become pinned tests, with module state recreated so they can't go flaky.", tags: ["Nemotron worker", "sandbox"]},
  {k: "docs", t: "Evidence-linked docs and report", d: "Docs where every observed claim cites a recorded run (checked mechanically), and a report that keeps each dimension separate and lists what is still unverified.", tags: ["Nemotron reasoner", "evidence"]},
];
const PROGRESS = [...STAGES.map(s => s.k), "done"];

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const ev = id => `<a href="#" class="ev" data-ev="${esc(id)}">${esc(id)}</a>`;
const evs = ids => (ids || []).map(ev).join(" ");
const pill = (cls, text) => `<span class="pill ${cls}">${esc(text)}</span>`;

let config = {};
let current = null;  // {id, report, files}

/* ---------------------------------------------------------------- home */
function renderSteps() {
  $("steps").innerHTML = STAGES.map(s => `<li><h3>${esc(s.t)}</h3><p>${esc(s.d)}</p>${
    s.tags.map(t => `<span class="tag ${t.startsWith("Nemotron") ? "model" : ""}">${esc(t)}</span>`).join("")}</li>`).join("");
  $("timeline").innerHTML = STAGES.map(s => `<li data-k="${s.k}"><span class="dot"></span>${esc(s.t)}</li>`).join("")
    + `<li data-k="done"><span class="dot"></span>Report ready</li>`;
}

async function loadConfig() {
  config = await (await fetch("/api/config")).json();
  const chips = config.llm_backend === "mock"
    ? ["models: offline mock"]
    : [`reasoner: ${config.reasoner}`, `worker: ${config.worker}`];
  chips.push(`sandbox: ${config.sandbox_backend}`);
  $("chips").innerHTML = chips.map(c => `<span class="chip">${esc(c)}</span>`).join("");
  $("pathOpt").hidden = !config.allow_local_paths;
  $("zipOpt").hidden = config.public_mode;
  $("publicNote").hidden = !config.public_mode;
  if (config.public_mode) $("runs").max = 20;
  $("ctaSample").hidden = !config.sample;
  renderDemos(config.demos || []);
}

function renderDemos(demos) {
  $("gallery").innerHTML = demos.map((d, i) => `<div class="card demo">
    <span class="num">DEMO ${i + 1} OF ${demos.length}</span>
    <h3>${esc(d.title)}</h3>
    <p>${esc(d.summary)}</p>
    <div class="tags">${d.shows.map(s => `<span class="tag">${esc(s)}</span>`).join("")}</div>
    <div class="acts">
      ${d.sample ? `<a class="btn sm primary" href="#/results/sample-${esc(d.id)}">View report</a>` : ""}
      <button class="btn sm" type="button" data-run="${esc(d.id)}">Run it live</button>
    </div></div>`).join("");
  $("demoSel").innerHTML = demos.map(d => `<option value="${esc(d.id)}">${esc(d.title)}</option>`).join("");
  $("demoSel").value = config.default_demo;
  describeDemo();
}

function describeDemo() {
  const d = (config.demos || []).find(x => x.id === $("demoSel").value);
  $("demoDesc").textContent = d ? d.summary + (d.needs_network ? " (installs a dependency, so it needs network access during setup.)" : "") : "";
}
$("demoSel").addEventListener("change", () => { form.source.value = "demo"; describeDemo(); });

const form = $("form");
form.addEventListener("change", () => {
  $("zipRow").hidden = form.source.value !== "zip";
  $("pathRow").hidden = form.source.value !== "path";
});

function markStage(stage) {
  const idx = PROGRESS.indexOf(stage);
  if (idx < 0) return;
  [...$("timeline").children].forEach((li, i) => {
    li.classList.toggle("done", i < idx || stage === "done");
    li.classList.toggle("active", i === idx && stage !== "done");
  });
}

function logLine(e, err) {
  const div = document.createElement("div");
  div.innerHTML = `<span class="t">${esc(e.t ?? "")}s [${esc(e.stage)}]</span> <span class="${err ? "e" : ""}">${esc(e.message)}</span>`;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}

form.addEventListener("submit", async e => {
  e.preventDefault();
  $("formErr").textContent = "";
  $("go").disabled = true;
  const res = await fetch("/api/analyze", {method: "POST", body: new FormData(form)});
  if (!res.ok) {
    const body = await res.json().catch(() => ({detail: res.statusText}));
    $("formErr").textContent = typeof body.detail === "string" ? body.detail : "Could not start the analysis.";
    $("go").disabled = false;
    return;
  }
  const {job} = await res.json();
  $("log").innerHTML = "";
  markStage("environment");
  const es = new EventSource(`/api/jobs/${job}/events`);
  es.onmessage = m => { const x = JSON.parse(m.data); markStage(x.stage); logLine(x, x.stage === "error"); };
  es.addEventListener("end", m => {
    es.close();
    $("go").disabled = false;
    const end = JSON.parse(m.data);
    if (end.status !== "done") { logLine({stage: "error", message: "Analysis failed: " + end.error}, true); return; }
    markStage("done");
    const link = document.createElement("div");
    link.innerHTML = `<a class="btn primary sm" href="#/results/${esc(job)}">Open the report →</a>`;
    $("log").appendChild(link);
    location.hash = `#/results/${job}`;
  });
});

/* ---------------------------------------------------------------- results */
const TABS = [
  ["overview", "Overview"], ["stability", "Stability"], ["repairs", "Repairs"],
  ["behavior", "Behavior"], ["docs", "Docs"], ["evidence", "Evidence"],
];

async function openResults(id) {
  if (!current || current.id !== id) {
    $("panel").innerHTML = `<p class="muted">Loading report…</p>`;
    const res = await fetch(`/api/jobs/${encodeURIComponent(id)}/report`);
    if (!res.ok) { $("panel").innerHTML = `<p class="err">Report not found. It may have expired when the server restarted.</p>`; return; }
    current = {id, report: await res.json(), files: {}};
  }
  const r = current.report;
  const demo = (config.demos || []).find(d => id === `sample-${d.id}` || (id === "sample" && d.id === config.default_demo));
  $("resKind").textContent = demo ? `Sample report · pre-computed run on the “${demo.title}” demo` : "Your analysis";
  $("resTitle").textContent = `Reliability report: ${r.repo}`;
  $("resMeta").textContent = `${r.generated_at} · ${r.seconds}s · sandbox: ${r.backends.sandbox} · models: ${r.models.reasoner} / ${r.models.worker}`;
  const base = `/jobs/${encodeURIComponent(id)}`;
  $("downloads").innerHTML = [
    ["report.html", "Standalone HTML"], ["report.json", "JSON"], ["docs.md", "docs.md"],
    ["tests/test_inherit_characterization.py", "Generated tests"],
  ].map(([p, l]) => `<a class="btn sm" href="${base}/${p}" target="_blank" rel="noopener">${l}</a>`).join("");
  const counts = {
    stability: r.stability.unstable.length, repairs: r.repairs.length,
    behavior: r.behavior.pinned, evidence: r.evidence.length,
  };
  $("tabs").innerHTML = TABS.map(([k, l]) =>
    `<button role="tab" data-tab="${k}">${l}${counts[k] !== undefined ? `<span class="n">${counts[k]}</span>` : ""}</button>`).join("");
  showTab("overview");
}

function showTab(tab, focusEvidence) {
  [...$("tabs").children].forEach(b => b.setAttribute("aria-selected", b.dataset.tab === tab));
  const r = current.report;
  const render = {overview, stability, repairs, behavior, docs, evidence}[tab];
  const out = render(r);
  if (out instanceof Promise) { $("panel").innerHTML = `<p class="muted">Loading…</p>`; out.then(h => { $("panel").innerHTML = h; after(tab, focusEvidence); }); }
  else { $("panel").innerHTML = out; after(tab, focusEvidence); }
}

function after(tab, focusEvidence) {
  if (tab === "evidence") {
    wireEvidenceTools();
    if (focusEvidence) {
      const d = document.getElementById("ev-" + focusEvidence);
      if (d) { d.open = true; d.scrollIntoView({block: "center"}); d.classList.add("flash"); }
    }
  }
}

function verifiedCount(r) { return r.repairs.filter(x => x.status === "verified").length; }

function overview(r) {
  const s = r.stability, b = r.behavior;
  const mock = r.backends.llm === "mock";
  return `
  ${mock ? `<div class="note" style="margin-bottom:16px">This run used the <b>offline mock model</b> instead of NVIDIA Nemotron, so test inputs were heuristic and no real diagnosis was attempted. Sandbox runs, bisection, verification and evidence are real.</div>` : ""}
  <div class="stats">
    <div class="card stat"><b>${s.unstable.length}</b><span>unstable test${s.unstable.length === 1 ? "" : "s"} in ${s.runs} shuffled runs</span></div>
    <div class="card stat"><b>${s.stable_observed}/${s.tests_total}</b><span>tests with no observed failures</span></div>
    <div class="card stat"><b>${verifiedCount(r)}/${r.repairs.length}</b><span>repairs verified by re-running</span></div>
    <div class="card stat"><b>${b.pinned}</b><span>behaviors pinned across ${b.functions_with_pins}/${b.functions_total} functions</span></div>
    <div class="card stat"><b>${r.docs.observed}</b><span>documented claims backed by evidence</span></div>
    <div class="card stat"><b>${r.evidence.length}</b><span>recorded sandbox runs</span></div>
  </div>
  <div class="grid2">
    <div class="card"><h3>Open uncertainties</h3><ul class="plain">${r.uncertainties.map(u => `<li>${esc(u)}</li>`).join("")}</ul></div>
    <div class="stack">
      ${environmentCard(r)}
      <div class="card"><h3>Why there is no single score</h3><p class="muted">Each dimension is reported on its own. A suite can be stable but shallow, or broad but flaky; collapsing them would hide exactly what you need to know.</p></div>
      <div class="card"><h3>Model usage</h3>${modelUsage(r)}</div>
    </div>
  </div>`;
}

function environmentCard(r) {
  const e = r.environment;
  if (!e) return "";
  const inv = r.investigations;
  const status = {not_needed: pill("n", "no third-party requirements"), installed: pill("ok", "installed"),
                  cached: pill("ok", "installed (cached)"), failed: pill("bad", "install failed")}[e.install_status] || "";
  return `<div class="card"><h3>Environment</h3>
    <p>${status} ${e.requirements.length ? `${e.requirements.length} requirement(s) from ${esc(e.sources.join(", "))} ${ev(e.install_evidence)}` : ""}</p>
    ${e.install_error ? `<p class="err">${esc(e.install_error)}</p>` : ""}
    ${e.missing_modules.length ? `<p class="err">Tests could not import: ${e.missing_modules.map(m => `<code>${esc(m)}</code>`).join(" ")}. Failures in those files are an environment problem, not flakiness.</p>` : ""}
    ${e.skipped.length ? `<details><summary class="small">${e.skipped.length} requirement line(s) not installed</summary><ul class="plain small">${e.skipped.map(s => `<li>${esc(s)}</li>`).join("")}</ul></details>` : ""}
    ${inv ? `<p class="muted small" style="margin-top:8px">Investigated ${inv.investigated} of ${inv.unstable} unstable test(s) (limit ${inv.limit}, most frequent failures first).</p>` : ""}
  </div>`;
}

function modelUsage(r) {
  if (!r.model_usage.length) return `<p class="muted">No model calls.</p>`;
  return `<div class="scroll"><table><tr><th>Role</th><th>Model</th><th>Calls</th><th>Tokens in/out</th><th>Avg latency</th></tr>${
    r.model_usage.map(u => `<tr><td>${esc(u.role)}</td><td><code>${esc(u.model)}</code></td><td class="num">${u.ok_calls}/${u.calls}</td>
    <td class="num">${u.prompt_tokens ?? 0} / ${u.completion_tokens ?? 0}</td><td class="num">${u.avg_latency}s</td></tr>`).join("")}</table></div>`;
}

function stability(r) {
  const s = r.stability;
  const seeds = s.seeds.length ? `${s.seeds[0]}–${s.seeds[s.seeds.length - 1]}` : "none";
  const unstable = s.unstable.map(u => {
    const cells = s.run_matrix.map(m => {
      const failed = m.failed.includes(u.test);
      return `<a href="#" data-ev="${esc(m.evidence_id)}" class="${failed ? "f" : "p"}" title="seed ${m.seed}: ${failed ? "failed" : "passed"} (${esc(m.evidence_id)})">${failed ? "✕" : ""}</a>`;
    }).join("");
    const setup = u.classification === "depends_on_earlier_test";
    const related = u.polluters.map(p => `<code>${esc(p)}</code>`).join(`<span class="arr">+</span>`);
    const chain = !u.polluters.length ? "" : setup
      ? `<div class="chain"><code>${esc(u.test)}</code><span class="arr">alone →</span>${pill("bad", "fails")}</div>
         <div class="chain">${related}<span class="arr">then</span><code>${esc(u.test)}</code><span class="arr">→</span>${pill("ok", "passes")}</div>`
      : `<div class="chain">${related}<span class="arr">then</span><code>${esc(u.test)}</code><span class="arr">→</span>${pill("bad", "fails")}</div>`;
    const kindPill = {order_dependent: "warn", depends_on_earlier_test: "warn", nondeterministic: "bad"}[u.classification] || "n";
    return `<div class="card">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${pill(kindPill, u.classification.replace(/_/g, " "))}<code>${esc(u.test)}</code></div>
      <p style="margin-top:8px">Failed <b>${u.fails} of ${u.runs}</b> shuffled runs. ${esc(u.note)}</p>
      <div class="matrix" aria-label="per-run outcomes">${cells}</div>
      <div class="legend">Each square is one shuffled run (seeds ${seeds}); click to open its recorded output.</div>
      ${chain ? `<h3 style="margin-top:14px">${setup ? "The earlier test it silently depends on, found by bisection" : "Minimal failing order found by bisection"}</h3>${chain}` : ""}
      <p class="small muted">Classification and bisection runs: ${evs(u.evidence_ids)}</p>
    </div>`;
  }).join("");
  const rows = s.per_test.map(t => {
    const total = t.passed + t.failed;
    const pct = total ? Math.round(100 * t.failed / total) : 0;
    const status = t.failed && t.passed ? pill("warn", "unstable") : t.failed ? pill("bad", "always failing") : pill("ok", "no failures observed");
    return `<tr><td><code>${esc(t.test)}</code></td><td>${status}</td><td class="num">${t.failed}/${total}</td><td><div class="bar2"><i style="width:${pct}%"></i></div></td></tr>`;
  }).join("");
  return `<div class="stack">
    <p class="muted">${s.tests_total} tests run ${s.runs} times in shuffled order (seeds ${seeds}). "No failures observed" is not proof of determinism: other orders, timing and environments were not tested.</p>
    ${unstable || `<div class="card">No unstable tests were observed.</div>`}
    <div class="card"><h3>All tests</h3><div class="scroll"><table><tr><th>Test</th><th>Result</th><th>Failed</th><th></th></tr>${rows}</table></div></div>
  </div>`;
}

function diffHtml(diff) {
  return `<pre class="code">${diff.split("\n").map(l => {
    const cls = l.startsWith("+++") || l.startsWith("---") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "";
    return cls ? `<span class="${cls}">${esc(l)}</span>` : esc(l);
  }).join("\n")}</pre>`;
}

function repairs(r) {
  if (!r.repairs.length) return `<div class="card">No order-dependent failures needed a repair.</div>`;
  const cls = {verified: "ok", not_verified: "warn", rejected: "bad", invalid_patch: "bad", no_patch: "n"};
  return `<div class="stack">${r.repairs.map(p => `<div class="card">
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${pill(cls[p.status] || "n", p.status.replace(/_/g, " "))}<code>${esc(p.victim)}</code></div>
    <div class="grid2" style="margin-top:12px">
      <div><h3>Diagnosis <span class="muted small">model-generated${p.cause ? ` · ${esc(p.cause.replace(/_/g, " "))}` : ""}${p.confidence ? ` · ${esc(p.confidence)} confidence` : ""}</span></h3><p>${esc(p.explanation || "No diagnosis.")}</p></div>
      <div><h3>Verification <span class="muted small">by re-running</span></h3><p>${esc(p.reason)}</p></div>
    </div>
    ${p.diff ? `<h3 style="margin-top:14px">Patch</h3>${diffHtml(p.diff)}` : ""}
    ${p.evidence_ids.length ? `<p class="small muted">${p.evidence_ids.length} verification runs: ${evs(p.evidence_ids)}</p>` : ""}
  </div>`).join("")}
  <p class="muted small">A repair is "verified" only if the minimal failing order passes and every shuffled run stays green. Patches that remove assertions are rejected without running.</p></div>`;
}

async function fetchText(path) {
  if (current.files[path] === undefined) {
    const res = await fetch(`/jobs/${encodeURIComponent(current.id)}/${path}`);
    current.files[path] = res.ok ? await res.text() : "";
  }
  return current.files[path];
}

async function behavior(r) {
  const b = r.behavior;
  const src = await fetchText("tests/test_inherit_characterization.py");
  const code = src.split("\n").map(l => l.trim().startsWith("#") ? `<span class="cmt">${esc(l)}</span>`
    : esc(l).replace(/(E-\d{4,})/g, m => `</span>${ev(m)}<span>`)).join("\n");
  const row = (k, v) => `<tr><td>${k}</td><td class="num">${v}</td></tr>`;
  return `<div class="stack">
    <div class="grid2">
      <div class="card"><h3>Coverage</h3><table>
        ${row("Functions with pinned behavior", `${b.functions_with_pins} / ${b.functions_total}`)}
        ${row("Behaviors pinned as tests", b.pinned)}
        ${row("State-changing calls pinned with isolation", b.stateful_isolated)}
        ${row("Excluded: non-deterministic output", b.nondeterministic_excluded)}
        ${row("Excluded: state that could not be isolated", b.stateful_excluded)}
        ${row(`Dropped by the ${b.gate_runs}-run gate`, b.generated_tests_dropped.length)}
        ${row("Generated suite passes on unmodified code", b.validation_passed ? pill("ok", "yes") + " " + ev(b.validation_evidence) : b.validation_passed === null ? "n/a" : pill("bad", "no"))}
      </table></div>
      <div class="card"><h3>Pinned behavior to review</h3>${b.flagged_for_review.length
        ? `<ul class="plain">${b.flagged_for_review.map(f => `<li><code>${esc(f.function)}</code> raises ${esc(f.outcome.exc_type)}(${esc(f.outcome.exc_message)}) ${evs(f.evidence_ids)}</li>`).join("")}</ul>`
        : `<p class="muted">Nothing flagged.</p>`}
        <p class="muted small" style="margin-top:10px">Characterization tests pin what the code does <i>today</i>, which may include bugs. Check these before treating them as a specification.</p></div>
    </div>
    <div class="card"><h3>Generated characterization tests</h3>
      <p class="muted small">Templated from recorded results (not written freehand by the model). Each test cites the runs it came from.</p>
      <pre class="code"><span>${code}</span></pre></div>
  </div>`;
}

function inlineMd(s) {
  return esc(s)
    .replace(/\[(E-\d{4,})\]\([^)]*\)/g, (_, id) => ev(id))
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*]+)\*/g, "<i>$1</i>");
}

function renderMd(text) {
  const out = [];
  let list = false;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const li = line.match(/^- (.*)$/);
    if (!li && list) { out.push("</ul>"); list = false; }
    if (/^## /.test(line)) out.push(`<h2>${inlineMd(line.slice(3))}</h2>`);
    else if (/^# /.test(line)) out.push(`<h1>${inlineMd(line.slice(2))}</h1>`);
    else if (li) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${inlineMd(li[1])}</li>`); }
    else if (line) out.push(`<p>${inlineMd(line)}</p>`);
  }
  if (list) out.push("</ul>");
  return out.join("\n");
}

async function docs(r) {
  const md = await fetchText("docs.md");
  return `<div class="stack">
    <div class="stats">
      <div class="card stat"><b>${r.docs.observed}</b><span>observed statements, each citing recorded runs</span></div>
      <div class="card stat"><b>${r.docs.inferred}</b><span>inferred statements (model interpretation, unverified)</span></div>
      <div class="card stat"><b>${r.docs.downgraded.length}</b><span>claims downgraded by the citation validator</span></div>
    </div>
    <div class="card md">${md ? renderMd(md) : `<p class="muted">No documentation was generated.</p>`}</div>
  </div>`;
}

function evidence(r) {
  const kinds = [...new Set(r.evidence.map(e => e.kind))].sort();
  return `<p class="muted">Every sandbox execution Inherit performed, in order. Everything the report says traces back to one of these.</p>
  <div class="evtools"><input type="search" id="evq" placeholder="Search command or output"><select id="evk"><option value="">All kinds</option>${
    kinds.map(k => `<option>${esc(k)}</option>`).join("")}</select><span class="muted small" id="evc"></span></div>
  <div id="evlist">${r.evidence.map(e => `<details class="evi" id="ev-${esc(e.id)}" data-kind="${esc(e.kind)}">
    <summary><code>${esc(e.id)}</code><span>${esc(e.kind)}</span>${pill(e.exit_code === 0 ? "ok" : "bad", "exit " + e.exit_code)}<span class="muted small">${e.duration}s${e.seed !== null ? " · seed " + e.seed : ""}</span></summary>
    <div class="body"><pre class="code">$ ${esc(e.command)}</pre>${e.order ? `<p class="small muted">order: ${e.order.map(esc).join(" → ")}</p>` : ""}${
      e.stdout ? `<pre class="code">${esc(e.stdout)}</pre>` : ""}${e.stderr ? `<pre class="code">${esc(e.stderr)}</pre>` : ""}</div></details>`).join("")}</div>`;
}

function wireEvidenceTools() {
  const q = $("evq"), k = $("evk");
  const apply = () => {
    const term = q.value.toLowerCase();
    let shown = 0;
    document.querySelectorAll("#evlist details").forEach(d => {
      const ok = (!k.value || d.dataset.kind === k.value) && (!term || d.textContent.toLowerCase().includes(term));
      d.hidden = !ok; shown += ok;
    });
    $("evc").textContent = `${shown} shown`;
  };
  q.addEventListener("input", apply); k.addEventListener("change", apply); apply();
}

document.addEventListener("click", e => {
  const run = e.target.closest("[data-run]");
  if (run) {
    form.source.value = "demo";
    $("demoSel").value = run.dataset.run;
    describeDemo();
    form.dispatchEvent(new Event("change"));
    location.hash = "#/try";
    $("try").scrollIntoView();
    return;
  }
  const tab = e.target.closest("[data-tab]");
  if (tab) { showTab(tab.dataset.tab); return; }
  const link = e.target.closest("[data-ev]");
  if (link && current) { e.preventDefault(); showTab("evidence", link.dataset.ev); }
});

/* ---------------------------------------------------------------- router */
function route() {
  const h = location.hash;
  const m = h.match(/^#\/results\/([\w-]+)/);
  $("viewHome").hidden = !!m;
  $("viewResults").hidden = !m;
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === h));
  if (m) { window.scrollTo(0, 0); openResults(m[1]); return; }
  const section = {"#/how": "how", "#/try": "try", "#/demos": "demos"}[h];
  if (section) document.getElementById(section).scrollIntoView();
  else window.scrollTo(0, 0);
}

renderSteps();
window.addEventListener("hashchange", route);
loadConfig().catch(() => {}).finally(route);  // route after config so sample reports know their demo
