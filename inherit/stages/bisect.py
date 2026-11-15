"""Isolate the minimal set of earlier tests that makes a victim test fail (delta debugging)."""

from __future__ import annotations

from typing import Callable, Sequence


def ddmin(items: Sequence[str], fails: Callable[[list[str]], bool]) -> list[str]:
    """Zeller's ddmin: shrink `items` to a 1-minimal list for which `fails` stays True.

    `fails(subset)` must return True when the failure still occurs with only `subset`
    as predecessors. Results are memoised, so each distinct subset runs once.
    """
    cache: dict[tuple[str, ...], bool] = {}

    def check(subset: list[str]) -> bool:
        key = tuple(subset)
        if key not in cache:
            cache[key] = fails(subset)
        return cache[key]

    current = list(items)
    if not check(current):
        raise ValueError("failure does not occur with the full predecessor list")
    n = 2
    while len(current) >= 2:
        size = -(-len(current) // n)  # ceil division
        chunks = [current[i : i + size] for i in range(0, len(current), size)]
        reduced = False
        for chunk in chunks:
            if check(chunk):
                current, n, reduced = chunk, 2, True
                break
        if not reduced:
            for i in range(0, len(current), size):
                complement = current[:i] + current[i + size :]
                if complement and check(complement):
                    current, n, reduced = complement, max(n - 1, 2), True
                    break
        if not reduced:
            if n >= len(current):
                break
            n = min(len(current), n * 2)
    if len(current) == 1 and check([]):
        return []
    return current
