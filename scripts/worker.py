#!/usr/bin/env python3
"""Detached worker: review one finished session and maybe induce a skill.

Runs after the session is over, never during it. Claude Code live-watches skill
directories, so writing mid-session would invalidate the cached system prefix and
turn a ~46k cache read into a ~46k cache write on every later turn.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import store  # noqa: E402
import evict  # noqa: E402
from clean import clean  # noqa: E402
from validate import check, render_skill_md  # noqa: E402
from review import (ask, list_existing_skills, loaded_skills, parse_draft,  # noqa: E402
                    render)

PLUGIN_ROOT = Path(__file__).parent.parent
DEFAULTS = {
    "mode": "off",                 # off | dry-run | auto
    "min_tool_calls": 2,
    "max_active_skills": 25,
    "review_timeout_seconds": 180,
    "model": "haiku",
    "enabled_projects": [],        # empty = every project
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    for path in (PLUGIN_ROOT / "config.json", store.data_dir() / "config.json"):
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    if cfg.get("mode") not in ("off", "dry-run", "auto"):
        cfg["mode"] = "off"        # unrecognised value must never enable the feature
    return cfg


def log(event: str, **fields) -> None:
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
    log_dir = store.data_dir() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "worker.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")


def process(payload: dict) -> str:
    cfg = load_config()
    transcript = payload.get("transcript_path") or ""
    project_dir = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id") or "unknown"

    if cfg["mode"] == "off":
        return "off"
    allowed = cfg.get("enabled_projects") or []
    if allowed and not any(project_dir.startswith(p) for p in allowed):
        log("skipped_project", project=project_dir); return "skipped_project"
    if not transcript or not Path(transcript).exists():
        log("no_transcript", path=transcript); return "no_transcript"

    digest = clean(transcript)
    if digest.tool_calls < cfg["min_tool_calls"]:
        log("too_small", tool_calls=digest.tool_calls); return "too_small"

    ledger = store.read_ledger()
    owned = store.owned_names(ledger)
    # A skill that was loaded and led to a finished session has earned its keep.
    used = [n.strip("- ") for n in loaded_skills(transcript).splitlines() if n.startswith("- ")]
    store.note_loads(used)

    prompt = (PLUGIN_ROOT / "prompts" / "review.sys.md").read_text(encoding="utf-8")
    prompt += "\n\n---\n\n" + render(
        PLUGIN_ROOT / "prompts" / "review.msg.md",
        project=project_dir,
        existing_skills=list_existing_skills(project_dir, owned),
        loaded_skills=loaded_skills(transcript),
        evidence=digest.text,
    )

    raw = ask(prompt, model=cfg["model"], timeout=cfg["review_timeout_seconds"])
    if raw is None:
        log("review_failed", session=session_id); return "review_failed"
    draft = parse_draft(raw)
    if draft is None:
        log("unusable_reply", session=session_id, head=raw[:200]); return "unusable_reply"
    if draft.action == "skip":
        log("skipped", session=session_id, rationale=draft.rationale[:300]); return "skipped"

    root = store.skills_root(draft.scope, project_dir)
    root.mkdir(parents=True, exist_ok=True)
    result = check(draft, root, owned=owned, existing=store.existing_names(project_dir),
                   active_count=len(ledger), max_active=cfg["max_active_skills"])
    if not result.ok:
        log("refused", session=session_id, skill=draft.name, reasons=result.reasons)
        return "refused"

    skill_md = render_skill_md(draft.name, draft.description, draft.body)
    if cfg["mode"] == "dry-run":
        pending = store.data_dir() / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        (pending / f"{draft.name}.md").write_text(skill_md, encoding="utf-8")
        log("dry_run", session=session_id, skill=draft.name, scope=draft.scope)
        return "dry_run"

    path = store.apply(draft.name, skill_md, scope=draft.scope, project_dir=project_dir)
    store.record(draft.name, scope=draft.scope, description=draft.description,
                 rationale=draft.rationale, project_dir=project_dir,
                 session_id=session_id, path=str(path), action=draft.action)
    evicted = evict.enforce(cfg["max_active_skills"])
    log("applied", session=session_id, skill=draft.name, scope=draft.scope,
        path=str(path), action=draft.action, evicted=evicted)
    return "applied"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: worker.py <payload.json>", file=sys.stderr)
        return 2
    payload_path = Path(sys.argv[1])
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log("bad_payload", error=str(exc)); return 1
    try:
        outcome = process(payload)
        log("done", outcome=outcome)
    except Exception as exc:  # noqa: BLE001 - a worker crash must never be silent
        log("crashed", error=repr(exc))
        return 1
    finally:
        payload_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
