"""Build the reliability report. Dimensions stay separate; there is no aggregate trust score."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, select_autoescape

from .config import Config
from .evidence import EvidenceStore

if TYPE_CHECKING:
    from .pipeline import AnalysisResult

EXCERPT = 1500


def build_report(result: "AnalysisResult", store: EvidenceStore, cfg: Config) -> dict[str, Any]:
    from .pipeline import unified_diff

    stab, char = result.stability, result.characterization
    cls = {c.test: c for c in result.classifications}
    diag = {d.victim: d for d in result.diagnoses}
    seeds = [r.seed for r in stab.runs]

    unstable = []
    for t in stab.unstable:
        c = cls.get(t)
        unstable.append({
            "test": t, "fails": stab.fail_counts[t], "runs": len(stab.runs),
            "classification": c.kind if c else "not investigated",
            "polluters": c.polluters if c else [], "note": c.note if c else "",
            "evidence_ids": c.evidence_ids if c else [],
        })

    repairs = []
    for r in result.repairs:
        d = diag.get(r.victim)
        repairs.append({
            "victim": r.victim, "status": r.status, "reason": r.reason,
            "cause": d.diagnosis.cause if d and d.diagnosis else "",
            "explanation": d.diagnosis.explanation if d and d.diagnosis else "",
            "confidence": d.diagnosis.confidence if d and d.diagnosis else "",
            "diff": unified_diff(Path(result.repo), r.patched_files) if r.patched_files else "",
            "runs": r.runs, "evidence_ids": r.evidence_ids,
        })

    claims = [c for e in result.docs for c in e.claims]
    downgraded = [d for e in result.docs for d in e.downgraded]
    behavior = {
        "functions_total": len(char.functions) if char else 0,
        "functions_with_pins": len({p.function.qualified for p in char.pinned}) if char else 0,
        "pinned": len(char.pinned) if char else 0,
        "flagged_for_review": [
            {"function": p.function.qualified, "test": p.test_name, "outcome": p.outcome, "evidence_ids": p.evidence_ids}
            for p in char.pinned if p.flagged
        ] if char else [],
        "nondeterministic_excluded": char.nondeterministic if char else 0,
        "stateful_isolated": sum(1 for p in char.pinned if p.mutated) if char else 0,
        "stateful_excluded": char.stateful_excluded if char else 0,
        "generated_tests_dropped": char.dropped if char else [],
        "gate_runs": char.gate_runs if char else 0,
        "failed_functions": char.failed_functions if char else {},
        "validation_passed": char.validation_passed if char else None,
        "validation_evidence": char.validation_evidence if char else "",
    }

    uncertainties = [
        f"Stability results cover {len(stab.runs)} shuffled runs (seeds {min(seeds)}-{max(seeds)}) in one "
        "sandbox environment. Tests with no observed failures may still fail under other "
        "orders, timing, operating systems or load." if seeds else "No stability runs were recorded.",
        "Characterization tests pin what the code does today, which may include bugs. Review them "
        "before treating them as a specification.",
    ]
    uncertainties += [
        f"{c.test}: {c.note}." for c in result.classifications if c.kind != "order_dependent"
    ]
    raised: dict[tuple[str, str], int] = {}
    for f in behavior["flagged_for_review"]:
        key = (f["function"], f["outcome"].get("exc_type", ""))
        raised[key] = raised.get(key, 0) + 1
    uncertainties += [
        f"{fn} raises {exc} for {n} recorded input(s); confirm this is intended."
        for (fn, exc), n in raised.items()
    ]
    uncertainties += [f"{fn}: no behavior recorded ({why})." for fn, why in behavior["failed_functions"].items()]
    inferred = sum(1 for c in claims if c.kind == "inferred")
    if inferred:
        uncertainties.append(f"{inferred} documentation statement(s) are model inferences and were not verified.")
    if len(stab.unstable) > len(result.classifications):
        uncertainties.append(
            f"{len(stab.unstable) - len(result.classifications)} unstable test(s) were not investigated "
            f"(limit: {result.max_investigations} per analysis, most frequently failing first)."
        )
    env = result.environment
    if env.install_status == "failed":
        uncertainties.insert(0, f"Dependency installation failed, so some code could not be imported: {env.install_error}")
    if env.missing_modules:
        uncertainties.insert(0, f"Tests could not import {', '.join(env.missing_modules)}. Failures in "
                                f"{', '.join(env.collection_errors) or 'those files'} reflect the environment, "
                                "not the code's reliability.")
    if env.skipped:
        uncertainties.append(f"{len(env.skipped)} requirement line(s) were not installed (only prebuilt wheels "
                             "from the package index are supported).")
    if not result.tests:
        uncertainties.insert(0, "No pytest tests were collected, so stability could not be assessed.")
    for r in result.repairs:
        if r.status != "verified":
            uncertainties.append(f"Repair for {r.victim} is {r.status}: {r.reason}")
    if cfg.llm_backend == "mock":
        uncertainties.insert(0, "This run used the offline mock model, not NVIDIA Nemotron: inputs were "
                                "heuristic and no real diagnosis was attempted.")
    if cfg.sandbox_backend == "local":
        uncertainties.insert(0, "Code ran WITHOUT container isolation (local backend).")

    evidence = [
        {
            "id": f"E-{e['id']:04d}", "kind": e["kind"], "command": e["command"],
            "exit_code": e["exit_code"], "duration": round(e["duration"] or 0, 2), "seed": e["seed"],
            "order": json.loads(e["test_order"]) if e["test_order"] else None,
            "stdout": (e["stdout"] or "")[:EXCERPT], "stderr": (e["stderr"] or "")[:EXCERPT],
        }
        for e in store.executions()
    ]

    return {
        "repo": Path(result.repo).name,  # never publish the host's absolute path
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(result.seconds, 1),
        "backends": {"llm": cfg.llm_backend, "sandbox": cfg.sandbox_backend},
        "models": {"reasoner": cfg.model_reasoner or "mock", "worker": cfg.model_worker or "mock"},
        "stability": {
            "runs": len(stab.runs), "seeds": seeds, "tests_total": len(result.tests),
            "unstable": unstable, "always_failing": stab.always_failing,
            "stable_observed": len(result.tests) - len(stab.unstable) - len(stab.always_failing),
            "per_test": [
                {"test": t, "passed": stab.pass_counts.get(t, 0), "failed": stab.fail_counts.get(t, 0)}
                for t in result.tests
            ],
            "run_matrix": [
                {"seed": run.seed, "evidence_id": run.evidence_id,
                 "failed": sorted(t for t, o in run.outcomes.items() if o in ("FAILED", "ERROR"))}
                for run in stab.runs
            ],
        },
        "environment": {
            "sources": env.sources, "requirements": env.requirements, "skipped": env.skipped,
            "install_status": env.install_status, "install_evidence": env.install_evidence,
            "install_error": env.install_error, "missing_modules": env.missing_modules,
            "collection_errors": env.collection_errors,
        },
        "investigations": {"limit": result.max_investigations, "investigated": len(result.classifications),
                           "unstable": len(stab.unstable)},
        "repairs": repairs,
        "behavior": behavior,
        "docs": {"observed": sum(1 for c in claims if c.kind == "observed"), "inferred": inferred,
                 "downgraded": downgraded},
        "uncertainties": uncertainties,
        "model_usage": [
            {**u, "avg_latency": round(u["avg_latency"] or 0, 2)} for u in store.llm_usage()
        ],
        "evidence": evidence,
    }


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inherit Report</title>
<style>
:root{--bg:#fbfbfa;--card:#fff;--fg:#1d1d1f;--muted:#5f6368;--line:#e3e3e0;--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--accent:#76b900;--code:#f3f3f1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111214;--card:#1a1b1e;--fg:#e8e8e6;--muted:#a0a3a8;--line:#2c2e33;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--code:#22242a}}
:root[data-theme="dark"]{--bg:#111214;--card:#1a1b1e;--fg:#e8e8e6;--muted:#a0a3a8;--line:#2c2e33;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--code:#22242a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:0 0 12px}.muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:20px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:16px}
.stat b{display:block;font-size:24px}.stat span{color:var(--muted);font-size:13px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid currentColor}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
code,pre{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}pre{background:var(--code);padding:10px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;margin:6px 0}
a{color:inherit;text-decoration-color:var(--accent);text-underline-offset:2px}
ul{padding-left:20px;margin:6px 0}details summary{cursor:pointer}.scroll{overflow-x:auto}
</style></head><body><main>
<h1>Inherit reliability report</h1>
<div class="muted"><code>{{ r.repo }}</code> · {{ r.generated_at }} · {{ r.seconds }}s · sandbox: {{ r.backends.sandbox }} · models: {{ r.models.reasoner }} / {{ r.models.worker }}</div>
<p class="muted">Each dimension is reported separately. There is deliberately no single trust score: a suite can be stable but shallow, or broad but flaky.</p>

<div class="grid">
<div class="card stat"><b>{{ r.stability.unstable|length }}</b><span>unstable tests in {{ r.stability.runs }} shuffled runs</span></div>
<div class="card stat"><b>{{ r.behavior.pinned }}</b><span>behaviors pinned across {{ r.behavior.functions_with_pins }}/{{ r.behavior.functions_total }} functions</span></div>
<div class="card stat"><b>{{ r.repairs|selectattr("status","equalto","verified")|list|length }}/{{ r.repairs|length }}</b><span>repairs verified by re-running</span></div>
<div class="card stat"><b>{{ r.uncertainties|length }}</b><span>open uncertainties</span></div>
</div>

<section class="card"><h2>Stability</h2>
<p class="muted">{{ r.stability.tests_total }} tests, {{ r.stability.runs }} runs, seeds {{ r.stability.seeds|first }}–{{ r.stability.seeds|last }}. {{ r.stability.stable_observed }} tests had no observed failures (not proof of determinism).</p>
{% if r.stability.unstable %}<div class="scroll"><table><tr><th>Test</th><th>Failed</th><th>Classification</th><th>Polluter(s)</th><th>Evidence</th></tr>
{% for u in r.stability.unstable %}<tr><td><code>{{ u.test }}</code></td><td>{{ u.fails }}/{{ u.runs }}</td><td>{{ u.classification }}<br><span class="muted">{{ u.note }}</span></td>
<td>{% for p in u.polluters %}<code>{{ p }}</code><br>{% endfor %}</td><td>{% for e in u.evidence_ids %}<a href="#{{ e }}">{{ e }}</a> {% endfor %}</td></tr>{% endfor %}</table></div>
{% else %}<p>No unstable tests observed.</p>{% endif %}
{% if r.stability.always_failing %}<p><span class="pill bad">always failing</span> {% for t in r.stability.always_failing %}<code>{{ t }}</code> {% endfor %}</p>{% endif %}
</section>

<section class="card"><h2>Repairs</h2>
{% for p in r.repairs %}<div style="margin-bottom:14px">
<span class="pill {{ 'ok' if p.status=='verified' else 'bad' if p.status in ('rejected','invalid_patch') else 'warn' }}">{{ p.status }}</span> <code>{{ p.victim }}</code>
<p><b>Diagnosis</b> <span class="muted">(model-generated: {{ p.cause }}, {{ p.confidence }} confidence)</span><br>{{ p.explanation }}</p>
<p><b>Verification</b><br>{{ p.reason }}</p>
{% if p.diff %}<details><summary>Patch</summary><pre>{{ p.diff }}</pre></details>{% endif %}
<details><summary>{{ p.evidence_ids|length }} verification runs</summary>{% for e in p.evidence_ids %}<a href="#{{ e }}">{{ e }}</a> {% endfor %}</details>
</div>{% else %}<p>No repairs attempted.</p>{% endfor %}
</section>

<section class="card"><h2>Behavior coverage</h2>
<table>
<tr><td>Functions with pinned behavior</td><td>{{ r.behavior.functions_with_pins }} / {{ r.behavior.functions_total }}</td></tr>
<tr><td>Behaviors pinned as tests</td><td>{{ r.behavior.pinned }}</td></tr>
<tr><td>State-changing calls pinned with isolation</td><td>{{ r.behavior.stateful_isolated }}</td></tr>
<tr><td>Excluded: non-deterministic output</td><td>{{ r.behavior.nondeterministic_excluded }}</td></tr>
<tr><td>Excluded: state that could not be isolated</td><td>{{ r.behavior.stateful_excluded }}</td></tr>
<tr><td>Generated tests dropped by the {{ r.behavior.gate_runs }}-run gate</td><td>{% for t in r.behavior.generated_tests_dropped %}<code>{{ t }}</code><br>{% else %}0{% endfor %}</td></tr>
<tr><td>Generated suite passes on unmodified code</td><td>{% if r.behavior.validation_passed %}<span class="pill ok">yes</span>{% elif r.behavior.validation_passed is none %}n/a{% else %}<span class="pill bad">no</span>{% endif %} {% if r.behavior.validation_evidence %}<a href="#{{ r.behavior.validation_evidence }}">{{ r.behavior.validation_evidence }}</a>{% endif %}</td></tr>
</table>
{% if r.behavior.flagged_for_review %}<p><b>Pinned behavior to review</b></p><ul>{% for f in r.behavior.flagged_for_review %}<li><code>{{ f.function }}</code> raises {{ f.outcome.exc_type }}({{ f.outcome.exc_message }}) {% for e in f.evidence_ids %}<a href="#{{ e }}">{{ e }}</a> {% endfor %}</li>{% endfor %}</ul>{% endif %}
</section>

<section class="card"><h2>Documentation</h2>
<p>{{ r.docs.observed }} observed statements (each cites recorded runs, checked for provenance) · {{ r.docs.inferred }} inferred statements (unverified) · {{ r.docs.downgraded|length }} downgraded by the validator. See <code>docs.md</code>.</p>
{% if r.docs.downgraded %}<ul>{% for d in r.docs.downgraded %}<li>{{ d }}</li>{% endfor %}</ul>{% endif %}
</section>

<section class="card"><h2>Open uncertainties</h2><ul>{% for u in r.uncertainties %}<li>{{ u }}</li>{% endfor %}</ul></section>

<section class="card"><h2>Model usage (NVIDIA Nemotron via Nebius Token Factory)</h2>
{% if r.model_usage %}<div class="scroll"><table><tr><th>Role</th><th>Model</th><th>Calls</th><th>OK</th><th>Prompt tok</th><th>Completion tok</th><th>Avg latency</th></tr>
{% for u in r.model_usage %}<tr><td>{{ u.role }}</td><td><code>{{ u.model }}</code></td><td>{{ u.calls }}</td><td>{{ u.ok_calls }}</td><td>{{ u.prompt_tokens }}</td><td>{{ u.completion_tokens }}</td><td>{{ u.avg_latency }}s</td></tr>{% endfor %}</table></div>
{% else %}<p>No model calls.</p>{% endif %}
</section>

<section class="card"><h2>Evidence ({{ r.evidence|length }} recorded runs)</h2>
{% for e in r.evidence %}<details id="{{ e.id }}"><summary><code>{{ e.id }}</code> {{ e.kind }} · exit {{ e.exit_code }} · {{ e.duration }}s{% if e.seed is not none %} · seed {{ e.seed }}{% endif %}</summary>
<pre>$ {{ e.command }}</pre>{% if e.order %}<div class="muted">order: {{ e.order|join(" → ") }}</div>{% endif %}
{% if e.stdout %}<pre>{{ e.stdout }}</pre>{% endif %}{% if e.stderr %}<pre>{{ e.stderr }}</pre>{% endif %}</details>{% endfor %}
</section>
</main>
<script>
// open the evidence entry a link points at
function openHash(){var el=document.getElementById(location.hash.slice(1));if(el&&el.tagName==="DETAILS"){el.open=true;el.scrollIntoView()}}
window.addEventListener("hashchange",openHash);openHash();
</script>
</body></html>"""


def render_html(report: dict[str, Any]) -> str:
    env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
    return env.from_string(TEMPLATE).render(r=report)
