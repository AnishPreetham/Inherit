# Inherit: Evidence-Driven Onboarding and Reliability Triage for Legacy Python Code

**Hackathon:** Nebius x NVIDIA Global AI Hackathon
**Track:** Coding and Agentic Engineering

## 1. The Problem

Developers regularly inherit Python code they did not write. Documentation is thin, the authors have moved on, and the tests are missing or unreliable. Some tests fail intermittently, so a red build may be a real bug or just noise, and a green build proves little. Without a trustworthy signal, every change feels risky, so teams avoid refactoring, delay upgrades, and re-run CI until it passes.

AI coding tools can read code and draft tests or documentation, but their output is usually *plausible* rather than *checked*. A generated doc can describe behavior the code does not have. A generated test can pass for the wrong reason. Neither tells the developer which parts of the output deserve trust.

## 2. Who It Helps

- Maintainers taking over under-documented open-source projects.
- Teams inheriting legacy services after turnover or reorganization.
- Developers and students learning an unfamiliar codebase.

## 3. Our Solution

Inherit is an autonomous agent that builds an inspectable, evidence-backed picture of a Python repository. It does **not** claim to prove the code correct. It records what it observed, under which conditions, and what remains unknown.

1. **Characterize behavior.** Runs selected functions in an isolated sandbox, records actual inputs and outputs, and generates characterization tests that pin down the observed behavior.
2. **Investigate unreliable tests.** Repeats tests and varies execution order to flag instability. For order-dependent failures, it narrows the failing order to the specific test that leaves behind shared state (the "polluter") and explains the suspected cause.
3. **Propose targeted repairs.** For supported causes, proposes a fix and re-runs the affected tests to check it. When evidence is insufficient, it reports the diagnosis and says so instead of guessing.
4. **Document with evidence.** Each behavioral statement links to the test or execution that supports it. Broader inferences are labeled as inferences.
5. **Report honestly.** The final report keeps dimensions separate (behaviors observed, tests generated, stability, repairs and their outcomes, open uncertainties). It deliberately does not collapse them into one trust score.

## 4. Scope and Limits

- **Python repositories using pytest** only in this version. The architecture isolates language-specific logic so other ecosystems could be added later; none are implemented.
- A passing result means "no failures observed" under the recorded runs, order variations, and environment. It does not mean "always deterministic". Every result reports the run count, conditions, and limitations.
- Automated repair supports a small set of causes (order-dependence through shared mutable state, and similar). Other flaky causes, such as external services or true concurrency races, are detected and described but not fixed automatically.
- A characterization test records what the code does *today*, not what it *should* do. A bug can be pinned as "expected" behavior, so the report flags suspicious pinned behavior for human review.
- Generated claims about function behavior are only as strong as the inputs tried. A single observation never supports a universal claim.

## 5. What Is Different

Related tools exist for each part: test generators (Pynguin, Hypothesis), plugins that repeat or shuffle tests (pytest-randomly, pytest-repeat), and research tools for flaky-test detection. Our contribution is the combination:

- characterization tests tied to recorded executions,
- a stability investigation that ends in a specific cause and a checked repair attempt, and
- documentation where each claim is traceable to evidence or labeled as inference,

in one workflow whose report separates what is observed from what is assumed.

## 6. How It Uses NVIDIA and Nebius

- **NVIDIA Nemotron on Nebius Token Factory** drives the agent. A larger Nemotron model handles reasoning-heavy steps (diagnosing instability, proposing repairs). Smaller Nemotron models handle high-volume steps (generating test inputs, triaging run logs).
- **Token Factory** latency matters because each repository needs many model calls in an observe, hypothesize, run, re-check loop. The app reports per-model call counts and latency.
- Code executes in isolated containers with networking disabled, because the tool runs unfamiliar code.

## 7. Expected Outcome

A working web application and CLI that accepts a Python repository and returns:

- characterization tests with recorded executions,
- unstable tests with evidence and suspected causes,
- checked repairs where supported,
- evidence-linked documentation, and
- a multi-dimensional reliability report.

## 8. Success Criteria

- On the bundled demo repository, the pipeline runs end to end without manual steps.
- It detects the planted order-dependent flaky test and isolates the correct polluter test.
- A proposed repair makes the previously failing order pass, verified by repeated randomized-order runs.
- Every documentation claim has either an evidence link or an "inferred" label.
- The report states the number of runs and the conditions behind every stability result.
