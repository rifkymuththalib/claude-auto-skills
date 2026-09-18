#!/usr/bin/env python3
"""Run the reviewer prompt over the cases N times and report a pass rate.

Not CI-safe: it costs tokens and the verdicts are non-deterministic. This exists
to compare two prompt versions over several runs, not to gate a commit.

  python3 evals/run_eval.py --runs 3 [--case quiet-second-step]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

from cases import CASES              # noqa: E402
from review import ask, parse_draft, render  # noqa: E402


def verdict(digest: str, project: str, timeout: int, model: str) -> str:
    msg = render(ROOT / "prompts" / "review.msg.md", project=project,
                 existing_skills="(none)", loaded_skills="(none)", evidence=digest)
    raw = ask((ROOT / "prompts" / "review.sys.md").read_text(encoding="utf-8")
              + "\n\n---\n\n" + msg, model=model, timeout=timeout)
    if raw is None:
        return "ERROR"
    draft = parse_draft(raw)
    if draft is None:
        return "UNUSABLE"
    return "SKIP" if draft.action == "skip" else "PROPOSE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--case", default=None)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    selected = [c for c in CASES if args.case in (None, c["name"])]
    if not selected:
        print(f"no case named {args.case}", file=sys.stderr)
        return 2

    hits: dict[str, int] = defaultdict(int)
    total = 0
    passed = 0
    for case in selected:
        got = []
        for _ in range(args.runs):
            v = verdict(case["digest"], "/tmp/eval-project", args.timeout, args.model)
            got.append(v)
            total += 1
            if v == case["expect"]:
                passed += 1
                hits[case["name"]] += 1
        mark = "ok " if hits[case["name"]] == args.runs else ("~  " if hits[case["name"]] else "MISS")
        score = hits[case["name"]]
        print(f"{mark} {case['name']:28} expect={case['expect']:7} "
              f"{score}/{args.runs}  {got}")

    print(f"\n{passed}/{total} across {len(selected)} cases x {args.runs} runs")
    skips = [c for c in selected if c["expect"] == "SKIP"]
    if skips:
        sp = sum(hits[c["name"]] for c in skips)
        print(f"SKIP precision (the bar that matters): {sp}/{len(skips) * args.runs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
