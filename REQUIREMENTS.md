# Requirements

Priority: **M** = must have for submission, **S** = should have, **C** = could have.
Status: **Done** = implemented and covered by tests; **Done\*** = implemented, verified only with the offline mock model (real Nemotron calls pending Token Factory access).

## Functional

| ID | Requirement | Pri | Status | Where |
|---|---|---|---|---|
| F1 | Accept a Python repo using pytest (local path, bundled demo, or uploaded zip) | M | Done | `server.py`, `__main__.py` |
| F2 | Discover tests and public functions, ignoring tests and vendored folders | M | Done | `stages/discover.py`, `stages/characterize.py` |
| F3 | Run repo code only in a Docker sandbox: no network, CPU/memory/PID/time limits, on a copy | M | Done | `sandbox.py`, `sandbox/Dockerfile` |
| F3a | Install declared third-party requirements in a separate, wheel-only step (the only networked step) and report import problems as environment issues | M | Done | `stages/environment.py`, `sandbox.py` |
| F4 | Generate candidate inputs for functions via Nemotron (small model) | M | Done\* | `stages/characterize.py` |
| F5 | Execute inputs and record output or exception, duration, module-state changes and environment reads as evidence | M | Done | `sandbox/probe.py` |
| F6 | Run each case twice and exclude non-deterministic outputs from pinned tests | M | Done | `stages/characterize.py` |
| F7 | Emit pytest characterization tests from recorded outputs, isolated from shared state and environment | M | Done | `stages/characterize.py` |
| F7a | Gate generated tests: drop any that fail or leak state into the existing suite (bisected) | S | Done | `stages/characterize.py` |
| F8 | Run the existing suite N times with random ordering (default 20) and record per-test outcomes and seeds | M | Done | `stages/stability.py` |
| F9 | Flag tests whose outcomes differ across runs or orderings | M | Done | `stages/stability.py` |
| F10 | For order-dependent failures, bisect the preceding order to the minimal polluter | M | Done | `stages/bisect.py` |
| F10a | Investigate several unstable tests per analysis (configurable, default 10, most frequent first) | S | Done | `pipeline.py` |
| F10b | Distinguish nondeterministic tests and tests that depend on another test's setup; trace the latter to the state-setter | S | Done | `stages/stability.py` |
| F10c | Seven bundled demo projects with declared expectations and pre-computed reports | S | Done | `demos/`, `samples/`, `inherit/demos.py` |
| F11 | Ask Nemotron (large model) for a structured diagnosis from polluter, victim, imported code and a fresh failure | M | Done\* | `stages/diagnose.py` |
| F12 | Propose a patch; verify by re-running the failing order and N shuffled runs; reject patches that weaken tests | S | Done (verification), Done\* (patch generation) | `stages/repair.py` |
| F13 | Markdown docs; each observed claim cites evidence, otherwise labeled "inferred" | M | Done\* | `stages/docs.py` |
| F14 | Downgrade doc claims citing missing, nonexistent or other-function evidence | S | Done | `stages/docs.py` |
| F15 | HTML and JSON report with separate dimensions and no aggregate score | M | Done | `report.py` |
| F16 | Report run counts, seeds, conditions and limitations for every stability result | M | Done | `report.py` |
| F17 | Flag suspicious pinned behavior (exceptions) for human review | C | Done | `stages/characterize.py` |
| F18 | Web UI with live progress and an interactive report | M | Done | `server.py`, `static/` |
| F19 | Headless CLI | S | Done | `__main__.py` |
| F20 | Per-model call counts, tokens and latency in the report | M | Done\* | `llm.py`, `report.py` |

## Non-functional

| ID | Requirement | Pri | Status |
|---|---|---|---|
| N1 | Demo run under 5 minutes | M | Done: about 80 s in Docker with the mock model; to re-measure with real Nemotron latency |
| N2 | No secrets in the repo; key read from environment | M | Done (`.env` is git- and docker-ignored) |
| N3 | Model IDs and base URL configurable via `.env` | M | Done |
| N4 | Model calls retry with backoff; failures degrade gracefully | M | Done |
| N5 | All executions logged to SQLite | M | Done |
| N6 | Seeds recorded for every randomized run | M | Done |
| N7 | Works on Windows, macOS and Linux with Docker | S | Done on Windows (Docker Desktop + WSL 2); Linux via the app image and VM script |
| N8 | Unit tests for bisection, evidence store, claim validator and more | S | Done: 61 tests |
| N9 | Hostable publicly: demo-only mode for container hosts, full mode for Docker VMs | S | Done: images tested locally; VM script linted, not yet run on a real VM |

## Out of scope

- Languages other than Python; test frameworks other than pytest.
- Proving correctness or determinism.
- Automatic repair of network, external-service, timing or true concurrency flakiness (these are detected and described).
- Dependencies that need building from source or private indexes.
- Large repositories (target: under about 50 files and 5k lines; every stability run is a full suite run).

## Submission checklist

- [ ] Token Factory access and real Nemotron run; regenerate `samples/` with `python -m inherit samples`
- [ ] Public repo with MIT license visible in the About section
- [x] README with setup, usage and NVIDIA/Nebius usage highlighted
- [ ] Hosted demo URL available through judging (Azure VM planned; see DEPLOY.md)
- [ ] Public YouTube video, 3 minutes or less
- [ ] Project description and track on Devpost
- [ ] Feedback on Nebius Token Factory and NVIDIA tools
- [ ] City selection if an IRL event was attended
