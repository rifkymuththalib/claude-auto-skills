---
description: Remove a skill that auto-skills created, along with its ledger entry.
argument-hint: <skill-name>
---

Remove the auto-generated skill named `$1`.

Run:

```bash
python3 -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts'); import store; print('removed' if store.forget('$1') else 'not an auto-generated skill')"
```

If it reports `not an auto-generated skill`, say so and stop: this plugin only ever
removes skills it created itself, never one the user wrote. On success, mention that a
copy was retained under the skill's `.versions/` directory.
