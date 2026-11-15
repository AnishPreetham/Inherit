# Architecture

This describes the code as built. File references are relative to the repository root.

## Overview

```
 Web app (inherit/server.py + static/)        CLI (python -m inherit)
                    \                           /
                     Pipeline (inherit/pipeline.py)
                               |
  environment → discover → stability → classify/bisect → diagnose → repair → characterize → docs → report
                               |                                   |
               Sandbox runner (inherit/sandbox.py)     LLM client (inherit/llm.py)
               Docker: no network, limits, non-root    Nebius Token Factory (OpenAI-compatible)
                               |                       roles: reasoner (large Nemotron), worker (small)
                     Evidence store (inherit/evidence.py, SQLite)
```

Every stage writes to the evidence store, and the report is built only from it: anything the report states traces back to a recorded execution (`E-0001`, ...), a finding, or a logged model call.

## Components

### Configuration (`inherit/config.py`)
Reads `.env`/environment. With no `NEBIUS_API_KEY`, the LLM backend is the offline mock (`inherit/mock.py`), which says so in every report.

### LLM client (`inherit/llm.py`)
OpenAI-compatible client pointed at `NEBIUS_BASE_URL`. Two roles map to two model IDs:
- **worker** (`MODEL_WORKER`, small Nemotron): proposes inputs for probing functions.
- **reasoner** (`MODEL_REASONER`, large Nemotron): diagnosis and patches, documentation.

Each call is logged (role, model, task, tokens, latency, success). Failures retry with exponential backoff. `complete_json` validates replies against a Pydantic schema and makes one repair attempt on invalid JSON.

### Sandbox (`inherit/sandbox.py`, `sandbox/`)
- Every run copies the repository into a fresh temp directory; the original is never modified. Patches and generated tests are injected only into that copy (`extra_files`).
- **Docker backend** (`inherit-sandbox` image: Python 3.11, pytest, pytest-randomly, `probe.py`): `--network none`, 512 MB, 1 CPU, 256 PIDs, non-root user, per-command timeout.
- **Local backend**: plain subprocess, no isolation. Used for tests and for the public demo mode, which only analyzes the bundled demo repository.
- `PYTHONPATH` includes the repo root, `src/` (src layout) and installed dependencies.
- **Dependency install** (`install_dependencies`): the only step with network access. It runs `pip install --only-binary=:all: --target <dir>` in a separate container, so only prebuilt wheels are accepted and no package build scripts run. The sandbox's own pytest tooling is pinned with a constraints file so a repository cannot replace it. The result is cached by requirement list and mounted read-only into later runs.
- `probe_batch` runs `sandbox/probe.py`, which imports one function and calls it once per input case in a single process. For each call it records the return value or exception, which module-level data changed (then restores it), the module state the call started from, and which environment variables it read (via a recording stand-in for `os.environ`, which `os.getenv` also uses).

### Evidence store (`inherit/evidence.py`)
SQLite tables: `executions` (kind, command, seed, test order, exit code, output, duration, metadata), `findings`, `claims` (`observed` or `inferred`, with evidence IDs), `llm_calls`.

## Pipeline stages (`inherit/stages/`)

1. **Environment** (`environment.py`). Gathers requirements from `requirements*.txt` and `pyproject.toml` (`[project].dependencies` plus test/dev extras). Lines that need more than a wheel from the index (editable installs, paths, VCS/URL requirements, nested `-r`) are skipped and listed. After collection, `No module named ...` errors are recorded as an environment finding, so tests that cannot import are not mistaken for flaky or broken tests.
2. **Discover** (`discover.py`). `pytest --collect-only` with randomization off.
3. **Stability** (`stability.py`). The full suite runs N times (default 20) with `--randomly-seed=<seed>`; per-test outcomes and the execution order are parsed from verbose output. Tests with mixed outcomes are *unstable*; tests that never pass are *always failing*.
4. **Classify and bisect** (`stability.py`, `bisect.py`). Runs use `--continue-on-collection-errors`, so one unimportable file doesn't stop the rest. For each unstable test (up to `INHERIT_MAX_INVESTIGATIONS`, default 10, most frequent failures first), the test is run alone 5 times:
   - **sometimes fails alone** → `nondeterministic` (randomness, time or I/O inside the test, not ordering);
   - **always fails alone** → take a shuffled run where it *passed*, and ddmin finds the minimal earlier tests it needs: `depends_on_earlier_test` (it relies on a state-setter). If none can be reproduced, it is `fails_in_isolation`;
   - **never fails alone** → replay the failing order twice. If it doesn't fail again, it is `not_reproducible`. Otherwise Zeller's **ddmin** shrinks the preceding tests to a 1-minimal set of polluters (it can be more than one test that must all run): `order_dependent`. If the failure stops reproducing mid-bisection, it is reclassified as `nondeterministic` instead of being blamed on order.

   Each probe is a sandbox run, and results are memoized.
5. **Diagnose** (`diagnose.py`). For `order_dependent` and `depends_on_earlier_test` tests. Reproduces the failure fresh (polluters then victim, or the victim alone), then sends the reasoner the related tests' and victim's sources, the repository files they import, and the failure output. The structured reply has a cause (`shared_mutable_state`, `module_level_cache`, `environment_variable_leak`, `relies_on_other_test_setup`, `unknown`), explanation, confidence, and search-and-replace edits. It is stored as a model-generated, unverified finding.
6. **Verify repair** (`repair.py`). Edits must target `.py` files inside the repository, match exactly once, and may only create new or empty files. A patch that reduces the number of assertions in any file is **rejected without running**. Otherwise the order that failed before must now pass (polluters then victim, or a setup-dependent victim on its own), and N shuffled full-suite runs must show no failures of the victim and no *new* failures elsewhere. Tests that were already unstable are reported separately, so one fix isn't blocked by an unrelated flaky test. The verdict names the seeds and what remains unverified.
7. **Characterize** (`characterize.py`). AST discovery of public top-level functions (outside tests). The worker proposes up to 8 input cases each. Every function is probed **twice** in separate processes, and only cases whose results match are pinned: non-deterministic results are excluded. Tests are **templated from the recorded results**, not written by the model. Before the call, each test recreates the recorded module state and environment variables with `monkeypatch`, so it neither depends on nor leaks into other tests. Exceptions are pinned and flagged for review.
   A **gate** then runs the existing suite 5 times shuffled without and with the generated tests, plus one fixed run with the generated tests first. Generated tests that fail are dropped. If an existing test newly fails only with generated tests present, ddmin finds which generated test leaks state, and that test is dropped. A final run confirms the generated suite passes on the unmodified code.
8. **Docs** (`docs.py`). The reasoner writes claims from the recorded observations only. A validator downgrades every `observed` claim that cites no evidence, a nonexistent ID, or evidence recorded for a different function. It checks provenance, not truth, and the docs say so.
9. **Report** (`report.py`). JSON and a standalone HTML file with separate dimensions: environment, stability (per-test counts and a per-run matrix), repairs (diagnosis, verification, diff), behavior coverage, docs, open uncertainties, model usage, and every recorded execution. There is deliberately no aggregate score. The repository is shown by folder name only, never by host path.

## Web app (`inherit/server.py`, `inherit/static/`)

- FastAPI. `POST /api/analyze` takes the bundled demo, an uploaded zip (≤10 MB, ≤2000 files, ≤30 MB extracted, path traversal rejected) or, with `INHERIT_ALLOW_LOCAL_PATHS=1`, a server path.
- One analysis at a time, an optional hourly cap, and pruning of old runs.
- Progress streams over Server-Sent Events. `/api/jobs/{id}/report` serves the JSON, and `/jobs/{id}/<file>` serves outputs, confined to the run's folder.
- **Public mode** (`INHERIT_PUBLIC_MODE=1`): demo repository only, at most 20 runs, 6 analyses per hour.
- Bundled demo projects are discovered from `demo_repo/` and `demos/*/` by their `demo.json` (`inherit/demos.py`). Each pre-computed report in `samples/<id>/` is served as job `sample-<id>`. `check_report` compares a report with the demo's declared expectations, and both `python -m inherit samples` and `tests/test_demos.py` use it.
- The single-page front end has a landing page, a how-it-works section, the live analyzer, and a results view with tabs. Every evidence ID is a link that opens the recorded run.

## Deployment
- `Dockerfile` builds the app in public mode, e.g. for Hugging Face Spaces.
- `docker-compose.yml` runs full mode on a Docker host. The app drives the host's Docker through its socket, and temp copies live in `/srv/inherit/tmp`, mounted at the same path so sandbox bind-mounts resolve.
- `deploy/setup-vm.sh` sets up an Ubuntu VM in one command, with optional HTTPS via Caddy. See `DEPLOY.md`.

## Key design decisions

- **Execution evidence first.** Model output (inputs, diagnoses, docs) is treated as a hypothesis, and only sandbox runs establish facts.
- **Deterministic search over guessing.** Polluters are found by ddmin, not by asking a model to read a traceback.
- **Templated tests.** Pinned assertions are generated from recorded results, so a test cannot claim behavior that was never observed.
- **Tools must not create flakiness.** State and environment are recreated per generated test, and the gate removes any that still interfere.
- **No weakening.** Repairs that delete assertions are refused.
- **Honest scope.** Separate dimensions, run counts and seeds next to every stability claim, and an explicit list of uncertainties.
- **Least privilege.** Network access only during the wheel-only dependency install. Target code is never imported by the host.
