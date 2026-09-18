# auto-skills

A Claude Code plugin that reads each finished session, decides whether it taught
anything genuinely reusable, and writes the good ones out as validated
`SKILL.md` files.

It is deliberately reluctant. Most sessions teach nothing, and every skill it
creates costs context on every future turn — so skipping is the normal answer.

## Why reluctance is the whole design

A skill's `description` sits in the model's context on **every turn of every
session in its scope, forever**, whether or not it is ever used. It only repays
that if it makes the agent *act in fewer turns* — not merely understand
something sooner.

Measured on a real 237-turn session:

| | |
|---|---|
| Static prefix re-read every turn | 46,290 tok — **24% of the session's 45.1M** |
| Average context per API call | ~190k |
| Cost of one avoided turn | ~190k input tokens |
| Cost of a 25-skill catalogue | ~1,500 tok × every turn |
| Cost of one review | ~65k (40k digest + 24k nested-session prefix) |

So one skill that removes a ten-turn investigation returns ~1.9M tokens, against
a few hundred thousand of standing cost. The upside is real but not enormous —
expect **3–6% on long sessions** — and it turns negative fast if the reviewer
proposes eagerly. Hence the bias toward skipping.

## How it works

```
SessionEnd (async, ~8ms) ──▶ queue payload ──▶ detached worker
                                                   │
   gate ≥2 tool calls ──▶ clean transcript ──▶ review ──▶ validate ──▶ apply
   (idle sessions           960k → 40k tok      haiku      11 gates    atomic
    collapse to ~100 tok)   (96.7% smaller)                            + ledger
```

Three constraints shape it, all found by measurement rather than assumption:

- **Skills are live-watched.** A `SKILL.md` written mid-session loads without a
  restart, which changes the cached prefix and turns a 46k cache *read* into a
  46k cache *write* on every later turn. So writes happen only after the session
  has ended.
- **`SessionEnd` hooks are awaited on a budget** — 1.5s when no `timeout` is
  declared, 60s maximum. The hook therefore does nothing but queue a payload and
  detach; all real work happens in a separate process.
- **`--bare` breaks authentication.** It looks like the right recursion guard but
  skips credential loading, so the nested session fails with "Not logged in".
  Recursion is stopped by an `AUTOSKILLS_INNER` environment variable instead.

## Install

Requires Claude Code and Python 3.10+.

```bash
git clone https://github.com/rifkymuththalib/claude-auto-skills.git
claude plugin marketplace add ./claude-auto-skills
claude plugin install auto-skills@rifky-local
```

`--plugin-dir` also works for a single session, but a marketplace install is what
makes the plugin persist across sessions.

Verify it loaded, and confirm it adds nothing to your context:

```bash
claude plugin details auto-skills
#   Hooks (1)  SessionEnd  (harness-only — no model context cost)
#   Always-on:   ~0 tok   added to every session
```

It ships in **`dry-run`** mode: it reviews sessions and stages proposals under
`$CLAUDE_PLUGIN_DATA/pending/` without writing any skill. Run it that way for a
week and read what it would have created before turning it loose.

```bash
# when you are satisfied with what it proposes
echo '{"mode": "auto"}' > ~/.claude/plugins/data/auto-skills-rifky-local/config.json
```

## Configuration

`config.json`, either in the plugin directory or in `$CLAUDE_PLUGIN_DATA`
(the latter wins).

| Key | Default | Meaning |
|---|---|---|
| `mode` | `dry-run` | `off`, `dry-run` (stage only), or `auto` (write) |
| `min_tool_calls` | `2` | below this there is nothing to learn |
| `max_active_skills` | `25` | catalogue cap — evicted, not refused |
| `model` | `haiku` | reviewer model |
| `review_timeout_seconds` | `180` | |
| `enabled_projects` | `[]` | empty means every project |

An unrecognised `mode` falls back to `off`. An upgrade must never switch the
feature on for someone who did not ask for it.

## Commands

| Command | Does |
|---|---|
| `/skills-ledger` | what has been learned, how often each is used, catalogue token cost |
| `/skills-forget <name>` | remove a skill this plugin created (never one you wrote) |
| `/skills-replay [transcript]` | re-run the reviewer over a past session |

## Scope

The reviewer decides where each skill lives:

- `project` (default) — `<project>/.claude/skills/`. Costs tokens only in the
  repository that learned the lesson. Committable, so it travels with the repo.
- `user` — `~/.claude/skills/`. Costs tokens in every project, so it is reserved
  for lessons that hold regardless of the codebase.

## Safety

Skills written at `project` scope live inside the repository and may be
committed, so the validator treats credentials as a hard gate, not advice. Eleven
gates run in order; the name regex runs first because it is what makes the path
containment check meaningful:

name shape · description length · shadowing · body size · rendered size (chars
and bytes) · path containment · encoding and null bytes · credential patterns ·
high-entropy tokens · catalogue cap

The plugin only ever overwrites a skill it created itself, recorded in its own
ledger. Anything you wrote is never touched. Every write is atomic (`tmp` +
`os.replace`) so discovery never sees a half-written file, and the previous
version is kept under the skill's `.versions/` directory.

## Known limitations

- **The reviewer is non-deterministic at the decision boundary.** The same
  transcript can yield `create` on one run and `skip` on the next. Judge a prompt
  change by its pass *rate* over several runs — `python3 evals/run_eval.py
  --runs 3` — never by a single result.
- **It can capture a belief the session later refuted.** A long session contains
  wrong turns; a claim made confidently early and corrected later may survive
  into a draft. The prompt has rules for this and they help, but they do not
  eliminate it. This is the main reason to stay in `dry-run` at first.
- The reviewer runs on your Claude Code subscription, not a separate API key.

## Credit

Ported from the `auto_skills` plugin for Rezztor EAgent. The reviewer prompt is
the most valuable part and is largely that plugin's, adapted for Claude Code's
token model.

## Licence

MIT
