#!/usr/bin/env python3
"""Writing a skill to disk, and the ledger that records what we wrote.

Two rules carry the weight here:
  * The write is atomic (tmp + os.replace), because Claude Code live-watches
    skill directories and must never see a half-written SKILL.md.
  * We only ever overwrite a skill this plugin created. Anything else is the
    user's, and is never touched.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

LEDGER_NAME = "ledger.json"


def data_dir() -> Path:
    d = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or (Path.home() / ".claude" / "auto-skills"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def skills_root(scope: str, project_dir: str) -> Path:
    """Project scope keeps the token cost inside the repo that learned the lesson."""
    base = Path(project_dir) if scope == "project" else Path.home()
    return base / ".claude" / "skills"


def read_ledger() -> dict:
    path = data_dir() / LEDGER_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_ledger(ledger: dict) -> None:
    path = data_dir() / LEDGER_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def owned_names(ledger: dict | None = None) -> set[str]:
    return set((ledger if ledger is not None else read_ledger()).keys())


def existing_names(project_dir: str) -> set[str]:
    names: set[str] = set()
    for scope in ("project", "user"):
        root = skills_root(scope, project_dir)
        if root.is_dir():
            names |= {p.parent.name for p in root.glob("*/SKILL.md")}
    return names


def _keep_previous(skill_dir: Path) -> None:
    """History lives under a dot-prefixed dir: skill discovery skips path
    components starting with '.', so retained versions never join the catalogue."""
    current = skill_dir / "SKILL.md"
    if not current.exists():
        return
    versions = skill_dir / ".versions"
    versions.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (versions / f"{stamp}.md").write_text(current.read_text(encoding="utf-8"), encoding="utf-8")


def apply(name: str, skill_md: str, *, scope: str, project_dir: str) -> Path:
    root = skills_root(scope, project_dir)
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    _keep_previous(skill_dir)
    target = skill_dir / "SKILL.md"
    tmp = skill_dir / ".SKILL.md.tmp"
    tmp.write_text(skill_md, encoding="utf-8")
    os.replace(tmp, target)      # atomic: discovery never sees a partial file
    return target


def record(name: str, *, scope: str, description: str, rationale: str,
           project_dir: str, session_id: str, path: str, action: str) -> None:
    ledger = read_ledger()
    entry = ledger.get(name, {})
    entry.setdefault("created", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    entry.update({
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": scope,
        "description": description,
        "rationale": rationale,
        "project_dir": project_dir,
        "source_session": session_id,
        "path": path,
        "revisions": int(entry.get("revisions", 0)) + 1,
        "action": action,
    })
    entry.setdefault("loads", 0)
    entry.setdefault("last_loaded", None)
    ledger[name] = entry
    write_ledger(ledger)


def note_loads(names: list[str]) -> None:
    """A receipt that a skill was actually used. Eviction reads this."""
    if not names:
        return
    ledger = read_ledger()
    changed = False
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for name in names:
        if name in ledger:
            ledger[name]["loads"] = int(ledger[name].get("loads", 0)) + 1
            ledger[name]["last_loaded"] = now
            changed = True
    if changed:
        write_ledger(ledger)


def forget(name: str) -> bool:
    """Only ever removes a skill this plugin created."""
    ledger = read_ledger()
    entry = ledger.get(name)
    if not entry:
        return False
    path = Path(entry.get("path", ""))
    if path.name == "SKILL.md" and path.parent.name == name and path.exists():
        retired = path.parent / ".versions"
        retired.mkdir(parents=True, exist_ok=True)
        (retired / f"retired_{time.strftime('%Y%m%d_%H%M%S')}.md").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8")
        path.unlink()
        try:
            next(path.parent.glob("*"))
        except StopIteration:
            path.parent.rmdir()
    ledger.pop(name, None)
    write_ledger(ledger)
    return True
