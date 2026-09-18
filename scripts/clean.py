#!/usr/bin/env python3
"""Turn a Claude Code session transcript into a compact digest for review.

A raw .jsonl transcript is dominated by tool output that the reviewer does not
need: it needs to see what was *done*, not every byte that came back. Measured
on a real 237-turn session, this keeps all 269 tool calls while cutting
960k tokens to 32k (96.7%).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

# Enough of a tool input to see which file and which flags; enough of a result
# to see whether it worked. Raising these is the first thing to try if the
# reviewer starts producing vague skills.
MAX_TOOL_INPUT = 250
MAX_TOOL_RESULT = 300
# A reviewer that has to read more than this is being asked the wrong question.
MAX_DIGEST_CHARS = 200_000


@dataclass
class Digest:
    lines: list[str] = field(default_factory=list)
    tool_calls: int = 0

    @property
    def text(self) -> str:
        out = "\n".join(self.lines)
        if len(out) <= MAX_DIGEST_CHARS:
            return out
        # Keep the head and the tail: what was asked, and how it ended.
        head = out[: MAX_DIGEST_CHARS * 2 // 5]
        tail = out[-(MAX_DIGEST_CHARS * 3 // 5) :]
        return f"{head}\n\n[... middle of the session omitted ...]\n\n{tail}"


def _clip(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + f" …(+{len(value) - limit} chars)"


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(parts) if parts else json.dumps(content)[:MAX_TOOL_RESULT]
    return "" if content is None else json.dumps(content)


def clean(path: str) -> Digest:
    d = Digest()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") or {}
            role = message.get("role")
            content = message.get("content")

            if role == "user":
                if isinstance(content, str):
                    if content.strip():
                        d.lines.append(f"\n[user] {content.strip()}")
                    continue
                for block in content or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text", "").strip():
                        d.lines.append(f"\n[user] {block['text'].strip()}")
                    elif block.get("type") == "tool_result":
                        flag = " [error]" if block.get("is_error") else ""
                        body = _clip(_result_text(block), MAX_TOOL_RESULT)
                        if body:
                            d.lines.append(f"  -> result{flag}: {body}")

            elif role == "assistant":
                for block in content or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text", "").strip():
                        d.lines.append(f"\n[agent] {block['text'].strip()}")
                    elif block.get("type") == "tool_use":
                        d.tool_calls += 1
                        raw = json.dumps(block.get("input") or {}, ensure_ascii=False)
                        d.lines.append(f"\n- tool {block.get('name')}: {_clip(raw, MAX_TOOL_INPUT)}")
    return d


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: clean.py <transcript.jsonl> [--stats]", file=sys.stderr)
        return 2
    d = clean(sys.argv[1])
    if "--stats" in sys.argv:
        text = d.text
        print(f"tool_calls={d.tool_calls} chars={len(text)} approx_tokens={len(text)//4}")
    else:
        sys.stdout.write(d.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
