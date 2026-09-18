"""Cases for the reviewer prompt.

The bar is the SKIP cases, not the PROPOSE ones. A reviewer that proposes too
eagerly puts a description into every future turn's context forever; one that
skips too readily costs nothing but a missed opportunity. Weight accordingly.

Verdicts are noisy: the same case can go either way across runs. Judge a prompt
change on pass *rate* over several runs, never on a single result.
"""

CASES = [
    dict(
        name="one-off-question",
        expect="SKIP",
        why="Answering a question is work, not a lesson.",
        digest="""[user] what does helpers/skills.py do?
- tool Bash: {"command": "sed -n '1,60p' helpers/skills.py"}
  -> result: def get_skill_roots(agent=None): ...
[agent] It builds the ordered list of skill directories and de-dupes by first match.""",
    ),
    dict(
        name="named-file-edit",
        expect="SKIP",
        why="Editing a file the user named is ordinary work.",
        digest="""[user] fix the typo in README.md, 'recieve' -> 'receive'
- tool Edit: {"file_path": "README.md", "old_string": "recieve", "new_string": "receive"}
  -> result: applied
[agent] Done.""",
    ),
    dict(
        name="already-in-claude-md",
        expect="SKIP",
        why="Restating CLAUDE.md pays the cost twice and teaches nothing.",
        digest="""[user] run the tests
- tool Bash: {"command": "cat CLAUDE.md"}
  -> result: ## Commands\\npytest  # full suite\\nThe suite needs PostgreSQL.
- tool Bash: {"command": "pytest tests/"}
  -> result: 2348 passed
[agent] Suite passes. The DB requirement is documented in CLAUDE.md.""",
    ),
    dict(
        name="repetition-is-not-a-lesson",
        expect="SKIP",
        why="Re-exporting env vars is a harness constraint, not a missed step.",
        digest="""[user] run the failing test
- tool Bash: {"command": "export DB_URL=postgresql://localhost && pytest tests/test_a.py"}
  -> result: 1 passed
- tool Bash: {"command": "export DB_URL=postgresql://localhost && pytest tests/test_b.py"}
  -> result: 1 passed
- tool Bash: {"command": "export DB_URL=postgresql://localhost && pytest tests/test_c.py"}
  -> result: 1 passed
[agent] All three pass.""",
    ),
    dict(
        name="quiet-second-step",
        expect="PROPOSE",
        why="A paired step whose omission fails silently is the canonical skill.",
        digest="""[user] update the compose file
- tool Edit: {"file_path": "deploy/customer/docker-compose.yml"}
  -> result: applied
- tool Bash: {"command": "bash scripts/publish_installer.sh"}
  -> result: installer verification FAILED: COMPOSE_SHA256 mismatch
[agent] The installer pins a checksum of the compose file. Editing the compose file
without refreshing that constant makes the installer fail later, not at edit time.
- tool Bash: {"command": "new=$(sha256sum deploy/customer/docker-compose.yml | awk '{print $1}') && sed -i \\"s/^COMPOSE_SHA256=.*/COMPOSE_SHA256=\\\\\\"$new\\\\\\"/\\" deploy/customer/install.sh"}
  -> result: ok
- tool Bash: {"command": "bash scripts/publish_installer.sh"}
  -> result: verification passed
[agent] Both steps are required; the first alone fails quietly downstream.""",
    ),
    dict(
        name="surprising-constraint",
        expect="PROPOSE",
        why="Silent shadowing that cost real time; knowing it changes behaviour.",
        digest="""[user] why is my project skill not loading?
- tool Bash: {"command": "ls .claude/skills/"}
  -> result: code-review/
[agent] It is there, so something else must be winning.
- tool Bash: {"command": "grep -rn 'code-review' ~/.claude/skills/"}
  -> result: /home/u/.claude/skills/code-review/SKILL.md
[agent] Found it. A personal skill of the same name silently shadows the project one:
no warning is printed, the project file simply never loads. Renaming the project skill
fixed it immediately.""",
    ),
    dict(
        name="refuted-mid-session",
        expect="SKIP",
        why="The only candidate lesson was disproved before the session ended.",
        digest="""[agent] The hook is not firing, so --plugin-dir must not load plugin hooks at all.
- tool Bash: {"command": "ls ~/.claude/plugins/data/"}
  -> result: myplugin-inline/  myplugin-market/
[agent] Correction: it did fire. The output went to the plugin's own data directory and
I was looking in the wrong place. --plugin-dir loads hooks normally.""",
    ),
    dict(
        name="lookup-fact",
        expect="SKIP",
        why="A current value goes stale and anyone can read it.",
        digest="""[user] what version of the CLI is installed?
- tool Bash: {"command": "claude --version"}
  -> result: 2.1.274
[agent] 2.1.274.""",
    ),
]
