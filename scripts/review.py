#!/usr/bin/env python3
"""Ask a cheap model whether a finished session taught a reusable skill."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ACTIONS = {"create", "update", "skip"}
SCOPES = {"project", "user"}
MAX_LISTED_SKILLS = 60
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Draft:
    action: str
    rationale: str = ""
    scope: str = "project"
    name: str = ""
    description: str = ""
    body: str = ""


def _frontmatter(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError:
        return {}
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    key = None
    for line in match.group(1).splitlines():
        if re.match(r"^[A-Za-z0-9_-]+:", line):
            key, _, value = line.partition(":")
            key = key.strip()
            out[key] = value.strip().strip('"').strip("'")
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def skill_roots(project_dir: str) -> list[tuple[str, Path]]:
    return [
        ("project", Path(project_dir) / ".claude" / "skills"),
        ("user", Path.home() / ".claude" / "skills"),
    ]


def list_existing_skills(project_dir: str, owned: set[str]) -> str:
    rows: list[str] = []
    for _scope, root in skill_roots(project_dir):
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            meta = _frontmatter(skill_md)
            name = meta.get("name") or skill_md.parent.name
            desc = meta.get("description", "")
            mark = " `[yours]`" if name in owned else ""
            rows.append(f"- **{name}**{mark}: {desc}")
            if len(rows) >= MAX_LISTED_SKILLS:
                break
    return "\n".join(rows) if rows else "(none)"


def loaded_skills(transcript: str) -> str:
    """Receipts: which skills the agent actually loaded during the session."""
    names: list[str] = []
    try:
        fh = open(transcript, encoding="utf-8", errors="replace")
    except OSError:
        return "(none)"
    with fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") or {}
            if message.get("role") != "assistant":
                continue
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                    skill = (block.get("input") or {}).get("skill")
                    if skill and skill not in names:
                        names.append(skill)
    return "\n".join(f"- {n}" for n in names) if names else "(none)"


def render(template: Path, **fields: str) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in fields.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def parse_draft(raw: object) -> Draft | None:
    """Tolerant of fences and single-element arrays. Never repairs a bad draft."""
    data = raw
    if isinstance(data, str):
        text = data.strip()
        candidates = [text]
        # A skill body routinely contains its own ``` fences, so a non-greedy
        # fence match stops at an inner one and yields truncated JSON. Match the
        # OUTERMOST fence, and also try the widest brace span.
        fence = re.match(r"\A```(?:json)?\s*\n(.*)\n```\s*\Z", text, re.S)
        if fence:
            candidates.append(fence.group(1).strip())
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        else:
            return None
    if isinstance(data, list):
        if len(data) != 1:
            return None
        data = data[0]
    if not isinstance(data, dict):
        return None

    action = str(data.get("action", "")).strip().lower()
    if action not in ACTIONS:
        return None
    if action == "skip":
        return Draft(action="skip", rationale=str(data.get("rationale", ""))[:500])

    name = str(data.get("name", "")).strip().lower()
    description = str(data.get("description", "")).strip()
    body = str(data.get("body", "")).strip()
    if not (name and description and body):
        return None
    scope = str(data.get("scope", "project")).strip().lower()
    if scope not in SCOPES:
        scope = "project"
    return Draft(action, str(data.get("rationale", ""))[:500], scope, name, description, body)


def ask(prompt: str, *, model: str = "haiku", timeout: int = 120) -> str | None:
    """Run the reviewer in a nested Claude Code session.

    Recursion is stopped by AUTOSKILLS_INNER, which our SessionEnd hook checks
    before doing anything. `--bare` would also skip hooks but it skips credential
    loading too, so the nested session fails with "Not logged in" -- do not use it.

    The session runs from a neutral directory so no project CLAUDE.md, AGENTS.md
    or project skills load, and with --disable-slash-commands so the skill
    catalogue is left out. That is a 23.8k prefix instead of 46.3k.
    """
    env = dict(os.environ, AUTOSKILLS_INNER="1")
    neutral = Path.home() / ".claude" / "auto-skills-reviewer"
    neutral.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(
            ["claude", "-p", "--model", model, "--disable-slash-commands"],
            input=prompt, capture_output=True, text=True, timeout=timeout,
            env=env, cwd=str(neutral),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None
