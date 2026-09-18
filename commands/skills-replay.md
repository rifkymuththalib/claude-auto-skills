---
description: Re-run the auto-skills reviewer over a past session transcript, without waiting for a session to end.
argument-hint: [transcript.jsonl]
---

Re-run the reviewer over a finished session. If `$1` is empty, list the largest recent
transcripts under `~/.claude/projects/` and ask which one to use.

Build a payload and run the worker directly:

```bash
T="$1"
python3 - <<PY
import json, subprocess, os, pathlib
payload = {"session_id": "replay", "transcript_path": "$T",
           "cwd": os.getcwd(), "hook_event_name": "SessionEnd", "reason": "other"}
p = pathlib.Path(os.environ.get("CLAUDE_PLUGIN_DATA", pathlib.Path.home()/".claude"/"auto-skills"))
p.mkdir(parents=True, exist_ok=True)
f = p/"replay.json"; f.write_text(json.dumps(payload))
subprocess.run(["python3", "${CLAUDE_PLUGIN_ROOT}/scripts/worker.py", str(f)])
PY
```

Then report the last entry from the worker log
(`$CLAUDE_PLUGIN_DATA/log/worker.jsonl`) so the user can see the verdict and its reason.
