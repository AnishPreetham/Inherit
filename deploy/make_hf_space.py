"""Copy the files a Hugging Face Space needs into a folder (normally a clone of the Space repo).

    python deploy/make_hf_space.py ../inherit-space

The Space builds the root Dockerfile (public demo mode). Its README.md must start with front
matter that sets the SDK and port, so the project README is copied with that header added.
Existing files in the target are overwritten; its .git folder is left alone.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = ["inherit", "sandbox", "demo_repo", "demos", "samples"]
FILES = ["Dockerfile", "requirements.txt", "LICENSE", ".dockerignore", ".gitattributes"]
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.db", ".env")

FRONT_MATTER = """---
title: Inherit
emoji: 🧬
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Find flaky tests, trace their cause, verify repairs
---

"""


def main(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in DIRS:
        dest = target / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(ROOT / name, dest, ignore=IGNORE)
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    (target / "README.md").write_text(FRONT_MATTER + readme, encoding="utf-8", newline="\n")
    print(f"Space files written to {target}")
    print("Next: cd there, then  git add -A && git commit -m \"Deploy Inherit\" && git push")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python deploy/make_hf_space.py <space-folder>")
    main(Path(sys.argv[1]).resolve())
