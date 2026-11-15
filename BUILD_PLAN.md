# Build Plan and Status

Deadline: **Fri Oct 30, 2026, 10:00 am PT**. Judging: Dec 1–15, 2026.

## Done

| Phase | Deliverable | Verified by |
|---|---|---|
| 1. Foundations | Config, LLM client with retries and usage logging, Docker sandbox, SQLite evidence store | unit tests; Docker runs confirm no network and non-root |
| 2. Demo repo | `demo_repo/` with two planted order-dependent flakes (shared state, env-var leak), a weak test, an off-by-one, undocumented functions | analysis finds both flakes and their exact polluters |
| 3. Stability | Shuffled suite runs with recorded seeds; unstable / always-failing classification | tests + Docker run |
| 4. Bisection | ddmin polluter isolation; up to 10 investigations per analysis | unit tests (pure ddmin) and end to end |
| 5. Characterization | Probing twice, templated pinned tests with state and env isolation, leak-detecting gate | tests including a class-attribute leak bisected by the gate |
| 6. Diagnose + repair | Structured diagnosis prompt; patch verification; rejection of test-weakening patches | tests with good, weakening and ineffective patches |
| 7. Docs + report | Evidence-linked docs with citation validator; HTML/JSON report with separate dimensions | tests check every cited ID exists |
| 8. Web app | Landing page, live analyzer (SSE), tabbed results view, sample report | browser checks at desktop and phone width |
| 9. Dependencies | Wheel-only install in the one networked step; missing-module reporting | Docker run with `python-dateutil`; network-blocked test inside the run |
| 11. Demo gallery | Seven demo projects with declared expectations, a pre-computed report each, a gallery on the site; classification extended (nondeterministic, depends-on-earlier-test, multi-polluter) | every bundled report checked against its `demo.json` |
| 10. Hosting | Public-mode image, full-mode compose, one-command VM script | both images run locally; script passes shellcheck |

## Remaining

1. **Token Factory access** (blocked on billing). Then set `.env`, run `python -m inherit check`, and tune prompts against real Nemotron output for input generation, diagnosis/patch and docs.
2. **Regenerate the sample reports** with real models: `python -m inherit samples`. It rebuilds `samples/<id>/` for all seven demos and fails if any demo no longer shows what its `demo.json` promises.
3. **Deploy** to an Azure for Students VM with `deploy/setup-vm.sh`; check the URL from another network.
4. **FEEDBACK.md** on Token Factory, Nebius and Nemotron.
5. **Git**: commit, push to a public GitHub repo, and confirm the MIT license shows in the About section.
6. **Demo video** (under 3 minutes, public on YouTube).
7. **Devpost submission.**

### Contingency
If Token Factory access hasn't arrived by **Oct 29 midday PT**, contact the organizers and decide whether to submit with the mock and explain the blocker. Without a runtime Token Factory call, the project risks failing the Stage One pass/fail check.

## Demo video script (under 3 minutes, no copyrighted music)

| Time | Scene |
|---|---|
| 0:00–0:20 | The problem: an inherited repo with flaky CI and no docs |
| 0:20–0:40 | Start an analysis on the website; explain the sandbox and the two Nemotron roles |
| 0:40–1:15 | Stability tab: shuffled-run matrix, two flaky tests, bisection to the exact polluters |
| 1:15–1:50 | Repairs tab: Nemotron's diagnosis, the patch, and verification over 20 shuffled runs |
| 1:50–2:20 | Behavior and Docs tabs: pinned tests citing evidence, state isolation, the review flag |
| 2:20–2:45 | Evidence tab and open uncertainties: what is proven and what is not |
| 2:45–3:00 | Model usage panel (Token Factory), limitations, close |
