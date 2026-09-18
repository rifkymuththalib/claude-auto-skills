#!/usr/bin/env python3
"""Gates a draft must pass before it is allowed to become a live skill.

Ported from rezztor-eagent plugins/_ea_auto_skills/helpers/validate.py. Order is
load-bearing: the name regex is what makes the path containment check meaningful,
so it runs first. Every gate appends its own reason; nothing is ever repaired.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9-]+$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY_CHARS = 8000
MAX_SKILL_MD_CHARS = 10_000
MAX_SKILL_BYTES = 40_000
MAX_ACTIVE_SKILLS = 25

# Credential shapes. A skill is a file inside the repository and may be committed,
# so this is a hard gate, not advice.
SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(pass(word|wd)|secret|token|api[_-]?key|passphrase)\b\s*[:=]\s*\S{3,}"), "credential assignment"),
    (re.compile(r"(?i)://[^\s/@:]+:[^\s/@]{3,}@"), "credential in a URL"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "API key"),
    (re.compile(r"(?i)\b(gh[pousr]_[A-Za-z0-9]{20,})"), "GitHub token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\baws_secret_access_key\b"), "AWS secret"),
]


@dataclass
class Result:
    ok: bool = True
    reasons: list[str] = field(default_factory=list)
    target_dir: Path | None = None

    def fail(self, reason: str) -> None:
        self.ok = False
        self.reasons.append(reason)


def _shannon(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def high_entropy_tokens(text: str, *, threshold: float = 4.0, min_len: int = 20) -> list[str]:
    """A long, dense, random-looking token is a credential until proven otherwise."""
    found = []
    for token in re.findall(r"[A-Za-z0-9+/_=-]{%d,}" % min_len, text):
        if token.count("-") > 3 or token.count("_") > 3:
            continue  # kebab/snake identifiers, not secrets
        if token.count("/") > 1 or token.count(".") > 1:
            continue  # file paths and dotted names, not secrets
        if _shannon(token) >= threshold:
            found.append(token)
    return found


def render_skill_md(name: str, description: str, body: str) -> str:
    """A colon or bracket in a model-written sentence would otherwise produce YAML
    that parses as something else, or fails to parse and makes the skill vanish
    silently at discovery time. Quote and escape it."""
    escaped = description.replace("\\", "\\\\").replace('"', '\\"')
    escaped = " ".join(escaped.split())
    return f'---\nname: {name}\ndescription: "{escaped}"\n---\n\n{body.strip()}\n'


def check(draft, root: Path, *, owned: set[str], existing: set[str],
          active_count: int, max_active: int = MAX_ACTIVE_SKILLS) -> Result:
    result = Result()
    name, description, body = draft.name, draft.description, draft.body

    # 1. name shape -- this is what makes gate 6 meaningful
    if not name:
        result.fail("name is empty")
    else:
        if len(name) > MAX_NAME:
            result.fail(f"name is {len(name)} characters, over {MAX_NAME}")
        if not NAME_RE.match(name):
            result.fail("name must be lowercase letters, digits and hyphens only")
        if name.startswith("-") or name.endswith("-"):
            result.fail("name must not start or end with a hyphen")
        if "--" in name:
            result.fail("name must not contain consecutive hyphens")

    # 2. description
    if not description:
        result.fail("description is empty")
    elif len(description) > MAX_DESCRIPTION:
        result.fail(f"description is {len(description)} characters, over {MAX_DESCRIPTION}")

    # 3. shadowing -- only a skill we created may be revised
    if name and name in existing and name not in owned:
        result.fail(f"name would shadow the existing {name} skill")

    # 4/5. body and rendered size
    if not body:
        result.fail("body is empty")
    elif len(body) > MAX_BODY_CHARS:
        result.fail(f"body is {len(body)} characters, over {MAX_BODY_CHARS}")

    skill_md = render_skill_md(name or "x", description, body)
    if len(skill_md) > MAX_SKILL_MD_CHARS:
        result.fail(f"rendered SKILL.md is {len(skill_md)} characters, over {MAX_SKILL_MD_CHARS}")
    if len(skill_md.encode("utf-8")) > MAX_SKILL_BYTES:
        result.fail(f"rendered SKILL.md is {len(skill_md.encode('utf-8'))} bytes, over {MAX_SKILL_BYTES}")

    # 6. path containment
    target = (root / name).resolve() if name else None
    if target is not None:
        try:
            target.relative_to(root.resolve())
            result.target_dir = target
        except ValueError:
            result.fail("resolved path escapes the skills directory")

    # 7. encoding
    if "\x00" in skill_md:
        result.fail("SKILL.md contains a null byte")
    try:
        skill_md.encode("utf-8").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        result.fail("SKILL.md is not valid UTF-8")

    # 8. secrets -- fail closed, and never conflate "could not check" with "clean"
    try:
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(skill_md):
                result.fail(f"SKILL.md contains what looks like a {label}")
                break
        else:
            hits = high_entropy_tokens(skill_md)
            if hits:
                result.fail(f"SKILL.md contains a high-entropy token that may be a credential: {hits[0][:12]}…")
    except Exception as exc:  # noqa: BLE001 - a broken scan is not a clean scan
        result.fail(f"could not check for credentials: {exc}")

    # 9. library cap -- revising an existing skill is exempt
    if name and name not in existing and active_count >= max_active:
        result.fail(f"already holding {max_active} auto-generated skills")

    return result
