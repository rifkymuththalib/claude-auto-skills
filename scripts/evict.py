#!/usr/bin/env python3
"""Keep the catalogue inside its token budget.

A skill's description sits in the model's context on every turn of every session
in its scope, forever. Under auto-apply nobody is watching, so the cap must
evict rather than refuse -- otherwise the library silently stops learning the
moment it fills up.
"""
from __future__ import annotations

import store

# Roughly four characters per token; good enough for a budget report.
CHARS_PER_TOKEN = 4


def description_tokens(ledger: dict) -> dict[str, int]:
    return {n: (len(e.get("description", "")) + len(n) + 6) // CHARS_PER_TOKEN
            for n, e in ledger.items()}


def coldest_first(ledger: dict) -> list[str]:
    """Least used first; ties broken by least recently used, then oldest."""
    def key(name: str):
        e = ledger[name]
        return (int(e.get("loads", 0)), e.get("last_loaded") or "", e.get("updated") or "")
    return sorted(ledger, key=key)


def enforce(max_active: int) -> list[str]:
    ledger = store.read_ledger()
    evicted: list[str] = []
    for name in coldest_first(ledger):
        if len(store.read_ledger()) <= max_active:
            break
        if store.forget(name):
            evicted.append(name)
    return evicted


def report() -> str:
    ledger = store.read_ledger()
    if not ledger:
        return "No auto-generated skills yet."
    tokens = description_tokens(ledger)
    rows = ["| skill | scope | loads | ~tok | last used |", "|---|---|---|---|---|"]
    for name in sorted(ledger, key=lambda n: -tokens[n]):
        e = ledger[name]
        rows.append(f"| {name} | {e.get('scope','?')} | {e.get('loads',0)} | "
                    f"{tokens[name]} | {e.get('last_loaded') or 'never'} |")
    total = sum(tokens.values())
    rows.append(f"\n**{len(ledger)} skills, ~{total} tokens** added per turn in scope.")
    return "\n".join(rows)


if __name__ == "__main__":
    print(report())
