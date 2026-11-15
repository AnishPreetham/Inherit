# Inherit

**Know what you can trust in code you inherited.**

Inherit is an agent for legacy Python repositories. It runs the code in an isolated sandbox, finds tests that fail intermittently and the exact test that causes it, checks repairs by re-running them, and documents behavior only from what it actually observed. Every statement in its report links to a recorded execution.

Built for the **Nebius x NVIDIA Global AI Hackathon**, Coding and Agentic Engineering track, with **NVIDIA Nemotron** models served on **Nebius Token Factory**.

> **Status.** The pipeline, sandbox, web app and CLI work end to end and are covered by tests. The Nemotron integration is implemented (OpenAI-compatible client with two model roles) but has so far only been exercised with the built-in offline mock model; results from real Nemotron calls are pending Token Factory access. The bundled sample reports were produced with the mock and say so.

## Why

Inherited code usually comes with thin documentation and tests nobody trusts. Some tests fail only sometimes, so a red build may be a bug or noise. AI coding tools can draft tests and docs, but their output is plausible rather than checked. Inherit treats trust as the product: it separates what it observed from what it inferred, and says what remains unverified.

## How it works

| # | Stage | What happens | Model |
|---|---|---|---|
| 1 | Prepare environment | Install requirements from `requirements*.txt` / `pyproject.toml`, prebuilt wheels only. This is the only step with network access | none |
| 2 | Discover | Collect pytest tests. Import errors are reported as an environment problem, not as flaky or broken tests | none |
| 3 | Stability | Run the suite N times in shuffled order; record every seed and outcome | none |
| 4 | Classify and bisect | For each unstable test (up to 10 by default): replay the failing order; if it fails only after others, delta debugging (ddmin) shrinks the order to the minimal **polluter** test | none |
| 5 | Diagnose | Send polluter, victim, imported source and a fresh failure to the model; get a structured cause and search-and-replace patch | Nemotron **reasoner** |
| 6 | Verify repair | Apply the patch to a sandbox copy; **verified** only if the minimal failing order passes and N shuffled runs show no new failures. Patches that remove assertions are rejected | none |
| 7 | Characterize | Model proposes inputs; each function runs twice and only repeatable results become pinned tests. Each test recreates the module state and environment variables it was observed with, and a gate drops (and bisects) any generated test that still interferes | Nemotron **worker** |
| 8 | Docs and report | Docs where each "observed" claim must cite runs recorded for that function (checked mechanically) or is downgraded to "inferred"; a report with separate dimensions and no single score | Nemotron **reasoner** |

Code from the target repository runs only inside a Docker container with `--network none`, memory/CPU/PID limits and a non-root user. Patches are applied only to temporary copies. Details: [ARCHITECTURE.md](ARCHITECTURE.md).

## How it uses NVIDIA and Nebius

- **NVIDIA Nemotron (large model)** is the reasoner: diagnosis, repair proposals and documentation.
- **NVIDIA Nemotron (small model)** is the worker: high-volume input generation for probing functions.
- **Nebius Token Factory** serves both through its OpenAI-compatible API (`inherit/llm.py`). Every call is logged with model, tokens, latency and success, and shown in each report's *Model usage* section.
- Model IDs and the base URL are configured in `.env`; look up current Nemotron IDs in the Token Factory console.

## Requirements

- Python 3.11+
- Docker (Docker Desktop with WSL 2 on Windows)
- A Nebius Token Factory API key for real model calls (optional: without one, Inherit uses an offline mock model)

## Setup

```bash
git clone <repo-url>
cd inherit
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # add NEBIUS_API_KEY, NEBIUS_BASE_URL, MODEL_REASONER, MODEL_WORKER
docker build -t inherit-sandbox sandbox/
```

Rebuild the sandbox image after any change in `sandbox/`.

## Run

**Web app**

```bash
python -m uvicorn inherit.server:app --port 8000
```

Open http://localhost:8000. The site explains the project, lists the seven demo projects, runs one of them or an uploaded zip with live progress, and shows results in tabs: Overview, Stability, Repairs, Behavior, Docs and Evidence. Evidence IDs anywhere in the report open the recorded run. A pre-computed report for every demo is available immediately.

**CLI**

```bash
python -m inherit analyze demo_repo --out report
python -m inherit analyze path/to/repo --out report --runs 20 --repair-runs 20
python -m inherit analyze demo_repo --out report --mock     # force the offline mock model
python -m inherit check                                     # show effective configuration
```

**Hosting.** See [DEPLOY.md](DEPLOY.md): a public demo mode that runs on any container host (e.g. Hugging Face Spaces, free) and analyzes only the bundled demo, and a full mode for Docker VMs (e.g. Nebius AI Cloud) that accepts uploads with every run isolated.

## Outputs

| File | Contents |
|---|---|
| `report.json` / `report.html` | Stability, repairs, behavior coverage, docs, open uncertainties, model usage, and every recorded run |
| `docs.md` | Evidence-linked documentation |
| `tests/test_inherit_characterization.py` | Generated characterization tests, each citing its evidence |
| `patches/*.diff` | Proposed repairs as unified diffs |
| `evidence.db` | SQLite store of all executions, findings, claims and model calls |

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `NEBIUS_API_KEY` | | Token Factory key; if unset, the mock model is used |
| `NEBIUS_BASE_URL` | | Token Factory OpenAI-compatible base URL |
| `MODEL_REASONER` / `MODEL_WORKER` | | Nemotron model IDs for the two roles |
| `STABILITY_RUNS` | 20 | Shuffled suite runs |
| `INHERIT_MAX_INVESTIGATIONS` | 10 | Unstable tests to classify, bisect and repair per analysis (most frequent failures first) |
| `SANDBOX_BACKEND` | `docker` | `local` runs code **without isolation** (development only) |
| `SANDBOX_TIMEOUT_SECONDS` | 60 | Per-command timeout |
| `INHERIT_ALLOW_LOCAL_PATHS` | unset | `1` lets the web app analyze server paths (never enable publicly) |

## Demo projects

Seven small projects are bundled, each built to show a different part of Inherit. The website's **Demos** section lists them, with a pre-computed report for each (`samples/<id>/`) and a button to run it live. Each demo's `demo.json` records what it is expected to show, and `tests/test_demos.py` checks the bundled reports against it.

| Demo | Folder | What it shows |
|---|---|---|
| **shop** | `demo_repo/` | Shared-state polluter and an environment-variable leak; state and env isolation in generated tests; off-by-one flagged for review |
| **ledger** | `demos/ledger/` | Module-level cache polluter; a test using random amounts, classified as *nondeterministic* rather than blamed on ordering |
| **scheduler** | `demos/scheduler/` | A victim that fails only when **two** polluters both ran (bisection finds the pair); a genuine parsing bug reported as *always failing* |
| **plugins** | `demos/plugins/` | src/ layout; a test that only passes after another test did its setup, traced to that state-setter; a class-attribute polluter; the gate dropping a generated test that would leak |
| **dates** | `demos/dates/` | A real dependency (`python-dateutil`) installed from a wheel and used offline; a settings-module polluter |
| **vault** | `demos/vault/` | A dependency with no prebuilt wheel and an editable-install line: install fails safely, the missing module is reported as an environment problem, and the other tests still run |
| **textkit** | `demos/textkit/` | A healthy project: no unstable tests, reported carefully, with behavior still characterized and documented |

`dates` and `vault` contact the package index during the environment step; the rest run fully offline.

Run any demo from the CLI, e.g. `python -m inherit analyze demos/scheduler --out report`. To regenerate every bundled report: `python -m inherit samples`.

### The shop demo in detail

`demo_repo/` is a small `shop` package with planted problems:

- `test_reserve_all_apples` empties shared stock, so `test_opening_stock_levels` fails only when it runs afterwards (order-dependent through shared state);
- `test_euro_store_uses_eur` sets `SHOP_CURRENCY` and never unsets it, so `test_default_price_format` fails after it (order-dependent through an environment-variable leak);
- a discount test that never exercises the `quantity > 10` boundary (likely off-by-one);
- undocumented functions and a clean, stable module for contrast.

On this repo, Inherit finds both flaky tests and bisects each to its exact polluter. It pins 31 behaviors across 8 functions, including the state- and environment-dependent ones, without introducing new flaky tests. Given a correct patch, it verifies the fix across 20/20 shuffled runs.

## Limitations

- Python + pytest only. Other languages are not implemented. The Docker sandbox uses Python 3.11.
- Dependencies are installed only from prebuilt wheels on the public index. Editable installs, local paths, VCS URLs, private indexes and packages that must be compiled are skipped or fail, and the report says which. Imports that still fail are reported as an environment problem.
- Up to 10 unstable tests are investigated per analysis (configurable). Every stability run is a full suite run, so large suites take proportionally longer.
- Observed stability is not proof of determinism; reports state run counts, seeds and environment.
- Characterization tests capture current behavior, which may include bugs; exceptions are flagged for review.
- Generated tests recreate module-level data and the environment variables a call read. Other state (class attributes, files) is caught only if it breaks a test during the gate runs.
- Automated repair targets order-dependence through shared state. Network, timing and concurrency flakiness are detected and described, not fixed.
- The citation validator checks provenance, not truth: an observed claim covers only the inputs that were run.

## Tests

```bash
python -m pytest tests -p no:randomly
```

Tests use the local sandbox backend for speed; the same flows have been run through the Docker backend.

## Project layout

```
inherit/
  config.py  llm.py  sandbox.py  evidence.py  mock.py
  stages/    environment.py discover.py stability.py bisect.py characterize.py diagnose.py repair.py docs.py
  pipeline.py  report.py  server.py  __main__.py
  static/    index.html app.css app.js
sandbox/     Dockerfile, probe.py (runs inside the container)
demo_repo/   the shop demo project
demos/      six more demo projects (each with demo.json)
samples/     pre-computed report for every demo, shown on the website
tests/       tests for Inherit
```

See [PROBLEM_STATEMENT.md](PROBLEM_STATEMENT.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT. See [LICENSE](LICENSE).
