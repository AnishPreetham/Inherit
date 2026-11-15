"""Offline stand-in for Nemotron, used when no Token Factory key is configured.

It is deliberately simple and says so in its output: heuristic test inputs, docs that only
restate observations, and an "unknown" diagnosis with no patch. It lets the full pipeline
run end to end without network access; it is not a substitute for the real models.
"""

from __future__ import annotations

import itertools
import json
import re

INT_HINTS = re.compile(r"qty|quantity|count|limit|size|tier|n$|index|num|age|days")
FLOAT_HINTS = re.compile(r"price|amount|rate|total|cost|ratio|weight")
STR_HINTS = re.compile(r"item|name|title|text|s$|key|word|path|label|code")

INTS = [0, 1, 10, 11, -1]
FLOATS = [0.0, 10.0, 2.5]
STRS = ["", "abc", "Hello, World!", "apple"]


def _values(param: str) -> list:
    p = param.lower()
    if INT_HINTS.search(p):
        return INTS
    if FLOAT_HINTS.search(p):
        return FLOATS
    if STR_HINTS.search(p):
        return STRS
    return [1, "a"]


def _required_params(signature: str) -> list[str]:
    inner = signature[signature.find("(") + 1 : signature.rfind(")")]
    params = []
    for part in [p.strip() for p in inner.split(",") if p.strip()]:
        if "=" in part or part.startswith("*"):
            continue
        params.append(part.split(":")[0].strip())
    return params


def inputs_for(signature: str, max_cases: int = 6) -> list[dict]:
    params = _required_params(signature)
    if not params:
        return [{"args": [], "kwargs": {}}]
    combos = list(itertools.product(*[_values(p) for p in params]))
    step = max(1, len(combos) // max_cases)
    return [{"args": list(c), "kwargs": {}} for c in combos[::step][:max_cases]]


OBS_RE = re.compile(r"^- (.+) \[evidence: ([^\]]+)\]$")


def mock_handler(role: str, task: str, system: str, user: str) -> str:
    if task.startswith("inputs:"):
        sig = re.search(r"Function signature: (.+)", user)
        return json.dumps({"cases": inputs_for(sig.group(1) if sig else "f()")})
    if task.startswith("docs:"):
        claims = []
        for line in user.splitlines():
            m = OBS_RE.match(line.strip())
            if m:
                claims.append({"text": m.group(1), "kind": "observed",
                               "evidence_ids": [e.strip() for e in m.group(2).split(",")]})
        return json.dumps({"summary": "(offline mock: no model summary)", "claims": claims})
    if task.startswith("diagnose:"):
        return json.dumps({"cause": "unknown", "confidence": "low", "edits": [],
                           "explanation": "Offline mock model: no diagnosis. Configure Nebius Token Factory."})
    return "{}"
