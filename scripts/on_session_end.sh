#!/usr/bin/env bash
# SessionEnd hook. Must return immediately: Claude Code awaits SessionEnd hooks
# for only 1.5s when no per-hook timeout is declared, clamped to 60s at most.
# All real work happens in a fully detached worker so nothing is ever truncated.
set -u

# Recursion guard. The worker invokes `claude -p`, whose nested session fires
# SessionEnd again. `--bare` should already skip hooks; this is the second lock.
if [ "${AUTOSKILLS_INNER:-}" = "1" ]; then
  exit 0
fi

DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/auto-skills}"
mkdir -p "$DATA_DIR/queue" "$DATA_DIR/log"

payload="$(cat)"

# Stamp the payload and drop it in the queue. The worker owns everything after.
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
printf '%s\n' "$payload" > "$DATA_DIR/queue/$stamp.json"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$payload" >> "$DATA_DIR/log/hook.log"

WORKER="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/scripts/worker.py"
if [ -x "$WORKER" ] || [ -f "$WORKER" ]; then
  AUTOSKILLS_INNER=1 setsid nohup python3 "$WORKER" "$DATA_DIR/queue/$stamp.json" \
    >> "$DATA_DIR/log/worker.log" 2>&1 < /dev/null &
  disown 2>/dev/null || true
fi

exit 0
