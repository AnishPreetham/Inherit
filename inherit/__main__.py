"""CLI: python -m inherit analyze <repo> --out <dir>"""

from __future__ import annotations

import argparse
import dataclasses

from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(prog="inherit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="show effective configuration")
    an = sub.add_parser("analyze", help="analyze a Python repository that uses pytest")
    an.add_argument("repo")
    an.add_argument("--out", default="report")
    an.add_argument("--runs", type=int, default=None, help="shuffled stability runs (default from .env)")
    an.add_argument("--repair-runs", type=int, default=20)
    an.add_argument("--max-investigations", type=int, default=None,
                    help="unstable tests to classify and repair (default 10, or INHERIT_MAX_INVESTIGATIONS)")
    an.add_argument("--mock", action="store_true", help="use the offline mock model even if a key is set")
    sm = sub.add_parser("samples", help="regenerate the bundled report for every demo and check it")
    sm.add_argument("--only", nargs="*", help="demo ids to regenerate (default: all)")
    sm.add_argument("--runs", type=int, default=20)
    sm.add_argument("--mock", action="store_true")
    args = parser.parse_args()

    cfg = Config.from_env()
    if args.cmd == "check":
        print(f"llm_backend={cfg.llm_backend} sandbox_backend={cfg.sandbox_backend}")
        print(f"reasoner={cfg.model_reasoner or '(unset)'} worker={cfg.model_worker or '(unset)'}")
        return
    if args.mock:
        cfg = dataclasses.replace(cfg, llm_backend="mock")
    from .pipeline import run_analysis

    if args.cmd == "samples":
        regenerate_samples(cfg, args.only, args.runs)
        return
    run_analysis(args.repo, args.out, cfg, stability_runs=args.runs, repair_runs=args.repair_runs,
                 max_investigations=args.max_investigations)


def regenerate_samples(cfg: Config, only: list[str] | None, runs: int) -> None:
    import json
    import shutil
    import sys

    from .demos import SAMPLES_DIR, check_report, load_demos
    from .pipeline import run_analysis

    failed = []
    for demo_id, demo in load_demos().items():
        if only and demo_id not in only:
            continue
        out = SAMPLES_DIR / demo_id
        shutil.rmtree(out, ignore_errors=True)
        print(f"== {demo_id}: {demo['title']}", flush=True)
        run_analysis(demo["path"], out, cfg, stability_runs=runs)
        (out / "evidence.db").unlink(missing_ok=True)  # the report already contains the evidence
        problems = check_report(json.loads((out / "report.json").read_text(encoding="utf-8")), demo["expect"])
        for p in problems:
            print(f"   MISMATCH: {p}", flush=True)
        if problems:
            failed.append(demo_id)
    print("all samples behave as designed" if not failed else f"demos not behaving as designed: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
