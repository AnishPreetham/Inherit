"""Call one function with given arguments and print one JSON result line per call.

Usage:
  python probe.py <module> <function> '<json args list>' '<json kwargs dict>'
  python probe.py <module> <function> --batch '<json list of {"args": [...], "kwargs": {...}}>'

Runs inside the sandbox; the host never imports target code.
"""

import copy
import importlib
import json
import os
import sys
import time
import types
from collections.abc import MutableMapping


class _RecordingEnviron(MutableMapping):
    """Stands in for os.environ during a call and remembers which variables were read.

    os.getenv also goes through os.environ, so both access styles are recorded."""

    def __init__(self, real):
        self._real = real
        self.reads = {}

    def _note(self, key):
        if isinstance(key, str) and key not in self.reads:
            self.reads[key] = self._real.get(key)

    def __getitem__(self, key):
        self._note(key)
        return self._real[key]

    def get(self, key, default=None):
        self._note(key)
        return self._real.get(key, default)

    def __contains__(self, key):
        self._note(key)
        return key in self._real

    def __setitem__(self, key, value):
        self._real[key] = value

    def __delitem__(self, key):
        del self._real[key]

    def __iter__(self):
        return iter(self._real)

    def __len__(self):
        return len(self._real)

    def copy(self):
        return dict(self._real)


def _state_names(mod) -> list[str]:
    """Module-level data (not functions, classes or modules) that a call could mutate."""
    return [
        n for n, v in vars(mod).items()
        if not n.startswith("__")
        and not isinstance(v, (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, type))
    ]


def call_once(func, args, kwargs, mod=None) -> dict:
    """Call func once. If mod is given, report which module globals changed and restore them,
    so every call observes the state the module had right after import."""
    saved, before, unrestorable = {}, {}, []
    if mod is not None:
        for n in _state_names(mod):
            before[n] = repr(getattr(mod, n))
            try:
                saved[n] = copy.deepcopy(getattr(mod, n))
            except Exception:
                unrestorable.append(n)
    real_environ, recorder = os.environ, _RecordingEnviron(os.environ)
    env_snapshot = dict(real_environ)
    os.environ = recorder
    start = time.perf_counter()
    result: dict = {}
    try:
        value = func(*args, **kwargs)
        result.update(status="returned", repr=repr(value), type=type(value).__name__)
    except BaseException as exc:  # record everything, including SystemExit
        result.update(status="raised", exc_type=type(exc).__name__, exc_message=str(exc))
    finally:
        os.environ = real_environ
    result["duration"] = time.perf_counter() - start
    result["env_reads"] = recorder.reads
    if dict(real_environ) != env_snapshot:  # undo environment changes so later calls see the same state
        real_environ.clear()
        real_environ.update(env_snapshot)
    if mod is not None:
        # state the call observed, so generated tests can recreate it instead of trusting current state
        result["state_before"] = {n: r for n, r in before.items() if len(r) <= 2000}
        names = set(before) | set(_state_names(mod))
        mutated = sorted(n for n in names if before.get(n) != (repr(getattr(mod, n)) if hasattr(mod, n) else None))
        result["mutated"] = mutated
        result["restore_failed"] = any(n in unrestorable or n not in saved for n in mutated)
        for n in mutated:
            if n in saved:
                setattr(mod, n, copy.deepcopy(saved[n]))
    return result


def main() -> None:
    module_name, func_name = sys.argv[1], sys.argv[2]
    sys.path.insert(0, ".")
    if len(sys.argv) > 3 and sys.argv[3] == "--batch":
        cases = json.loads(sys.argv[4])
    else:
        cases = [{
            "args": json.loads(sys.argv[3]) if len(sys.argv) > 3 else [],
            "kwargs": json.loads(sys.argv[4]) if len(sys.argv) > 4 else {},
        }]
    try:
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
    except BaseException as exc:
        for i in range(len(cases)):
            print("INHERIT_PROBE " + json.dumps({
                "index": i, "module": module_name, "function": func_name,
                "status": "import_error", "exc_type": type(exc).__name__, "exc_message": str(exc),
            }))
        return
    for i, case in enumerate(cases):
        out = {"index": i, "module": module_name, "function": func_name}
        out.update(call_once(func, case.get("args", []), case.get("kwargs", {}), mod))
        print("INHERIT_PROBE " + json.dumps(out))


if __name__ == "__main__":
    main()
