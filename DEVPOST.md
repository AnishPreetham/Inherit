# Devpost submission draft

Copy each section into the matching Devpost field. Replace every `[PLACEHOLDER]` before submitting, and delete the notes in *italics*.

---

## Project name
Inherit

## Tagline (one line)
Know what you can trust in code you inherited: an agent that finds flaky tests, traces them to the test that causes them, verifies repairs, and documents only what it observed.

## Track
Coding & Agentic Engineering

## Links
- **Live demo:** [DEMO URL]
- **Source code:** [GITHUB REPO URL]
- **Video:** [VIDEO URL]

## Team
[TEAM MEMBER NAMES AND ROLES]

---

## Inspiration
Most developers spend more time working in code they inherited than code they wrote. Inherited Python projects tend to have thin docs and a test suite nobody fully trusts: some tests fail only sometimes, so a red build might be a real bug or just noise. AI coding tools can generate tests and docs quickly, but what they produce is *plausible*, not *checked*.

We wanted an agent whose output you can trust, because every claim it makes points back to something it actually ran.

## What it does
Point Inherit at a Python/pytest repository (or pick one of seven bundled demo projects) and it:

1. **Prepares the environment:** installs the project's dependencies from prebuilt wheels in an isolated step, and reports import problems as environment issues instead of blaming the tests.
2. **Measures stability:** runs the suite many times in shuffled order, recording every seed and outcome.
3. **Classifies each unstable test** as order-dependent, dependent on an earlier test's setup, nondeterministic, or failing on its own, by replaying failing orders and running tests alone.
4. **Finds the culprit:** delta debugging (ddmin) shrinks a failing order down to the minimal set of "polluter" tests, including failures that need *two* specific tests to run first.
5. **Diagnoses and repairs** with NVIDIA Nemotron, then **verifies** each patch by re-running the minimal failing order and many shuffled runs. Patches that weaken assertions are rejected.
6. **Characterizes behavior:** the model proposes inputs, each function is run twice, and only repeatable results become pinned regression tests. A gate drops any generated test that would itself become flaky.
7. **Writes docs and a report** where every "observed" claim must cite a recorded run (checked mechanically) or is downgraded to "inferred". The report has separate dimensions and no single score, plus a list of open uncertainties.

Everything is shown in a web app with live progress, a run matrix, polluter chains, repairs, pinned behaviors, docs and a full evidence log.

## How we built it
- **Models:** NVIDIA Nemotron on **Nebius Token Factory** via its OpenAI-compatible API, in two roles. A larger *reasoner* model handles diagnosis, repair and documentation. A smaller *worker* model handles high-volume input generation. Models used: [REASONER MODEL ID] and [WORKER MODEL ID]. Every call is logged with tokens and latency and shown in the report.
- **Sandbox:** target code runs only in a Docker container with no network, memory/CPU/PID limits and a non-root user, on a fresh copy of the repo for each run.
- **Pipeline:** Python, pytest + pytest-randomly, an AST-based function discovery step, and a probe that snapshots and restores module state and records environment-variable reads, so generated tests can recreate the conditions they were observed under.
- **Evidence store:** SQLite holding every execution, finding, claim and model call. Report claims link to execution IDs.
- **Web app:** FastAPI with server-sent events for live progress, and a single-page front end.
- **Demos:** seven small projects, each built to show one behavior: shared-state and environment leaks, a stale cache, a random test, a two-polluter failure, a src layout with hidden setup, a real third-party dependency, an uninstallable dependency, and a healthy project. Each declares its expected results, and our test suite checks the reports against them.

## Challenges we ran into
- **Telling flakiness apart:** a test that fails after another test, one that only *passes* after another test, and one that is just random look the same in a single run. We added isolation runs and replays so each gets the right label, and so bisection never chases a random failure.
- **Generated tests that become flaky:** pinning the behavior of stateful code produced tests that depended on order. We fixed this by snapshotting and restoring module state, recreating observed environment variables, and gating the generated tests with shuffled runs plus bisection to drop any that still leak.
- **Untrusted code and dependencies:** the network is needed to install packages but must never be available to the code under test. We separated a wheels-only install step from the no-network runs.
- **Access:** [DESCRIBE TOKEN FACTORY ACCESS / BILLING ISSUE AND HOW IT WAS RESOLVED]. We built an offline mock model behind the same interface so development never blocked on it.

## Accomplishments that we're proud of
- On every bundled demo, Inherit traces each order-dependent test to its exact polluter(s), including a failure that needs two specific tests to run first.
- Repairs are only called "verified" after re-running the failing order and many shuffled runs, never on the model's word.
- Reports are explicit about what was observed and what was only inferred, and say "none observed" rather than "none exist".
- Broken environments are reported honestly instead of being mistaken for broken tests.

## What we learned
- Precise, checkable tasks get the most out of the LLM: a structured diagnosis and a search-and-replace patch that the sandbox then verifies.
- Separating a large reasoning model from a small high-volume model keeps cost and latency down.
- [ADD ANYTHING YOUR TEAM LEARNED]

## What's next for Inherit
- Repair for timing- and concurrency-related flakiness, not just shared state.
- Running as a CI step that comments on pull requests with newly unstable tests.
- More languages (JavaScript/TypeScript with Jest, Java with JUnit).
- Capturing more kinds of state (class attributes, files) when generating tests.

## Built with
`python` `pytest` `fastapi` `docker` `sqlite` `nvidia-nemotron` `nebius-token-factory` `openai-api` `javascript` `html` `css`

---

*Before submitting, check:*
- *If Token Factory access never worked, replace the "How we built it" model line with an honest note (for example: "the Nemotron integration is implemented; the bundled reports were produced with an offline mock because Token Factory access was blocked"), and make sure the video says the same.*
- *The demo URL opens in a private window.*
- *The GitHub repo is public and has no `.env` file.*
- *The video plays when logged out.*
- *All teammates have accepted the Devpost invite.*
