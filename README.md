# Code Impact Guardian

Code Impact Guardian is a lightweight, repo-local skill template for safer code
changes.

It stays intentionally small:

- one repo-local skill folder
- one SQLite graph
- one fixed direct-edge workflow
- one unified CLI
- one export path for consumers

It is not a plugin.
It is not a platform product.
It is meant to be copied into another repository and used quickly.

## Fixed workflow

The workflow does not change:

1. build / refresh graph
2. generate impact report
3. allow code edits
4. update graph / report / evidence after edit
5. run relevant tests and record outcome

## Stage8 focus

Stage8 keeps the same lightweight shape and pushes it toward daily-driver use:

- smarter seed selection from `--changed-file` and `--changed-line`
- shorter `brief` reports and `brief` status by default
- machine-readable JSON impact reports for agents
- conservative incremental refresh when safe, full rebuild when not
- stronger TS/JS + React + SQL day-to-day value without splitting adapters

## Current support level

### Python

- stable regression baseline
- `file`, `function`, `test`, `rule`
- direct `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- real `coverage.py` path

### TS/JS family

- `.js`, `.ts`, `.jsx`, `.tsx`
- function declarations
- exported const arrow functions
- React function components
- custom hooks
- minimal class methods
- import / export / re-export / require / module.exports
- node:test / jest / vitest style detection
- real raw V8 coverage path

### SQL/PostgreSQL supplemental

- real supplemental adapter
- SQL files become `file` nodes
- PostgreSQL routines become `function` nodes
- SQL subtype stored in attrs via `sql_kind`
- high-confidence SQL `CALLS`
- high-confidence SQL test `COVERS`
- app-to-SQL query hints only become edges when confidence is high enough
- test outcome is real even when SQL coverage is unavailable

### Generic fallback

- file-level only
- still supports build / report / after-edit / test outcome
- never pretends to have function-level precision

## Development repo vs consumer install

This repository is the development source.

It contains:

- examples
- tests
- stage history
- fixtures used to validate the template

The consumer-facing install path is now:

1. copy only `.agents/skills/code-impact-guardian/` into the target repo
2. run `python .agents/skills/code-impact-guardian/cig.py setup --project-root .`

That single-folder install will generate:

- `AGENTS.md`
- `.gitignore`
- `.code-impact-guardian/config.json`
- `.code-impact-guardian/schema.sql`
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`
- `CONSUMER_GUIDE.md`

## Exporting the skill

### Full package export

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --out path/to/exported-skill
```

This keeps the stage6-style distribution package.

### Single-folder export

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --mode single-folder --out path/to/exported-skill
```

This produces only the folder that should be copied into:

```text
.agents/skills/code-impact-guardian/
```

## Recommended commands

### High-level commands

These are the main user-facing commands now:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file <path> --changed-line <path:line>
python .agents/skills/code-impact-guardian/cig.py finish --changed-file <path>
```

What they do:

- `setup` = init + write AGENTS.md + write .gitignore + write consumer docs + doctor + detect
- `analyze` = build/reuse graph + automatic task id + smart seed ranking + brief report
- `finish` = after-edit + recent task reuse + tests + handoff/status refresh

Useful flags:

- `--changed-line <path:line>` improves seed ranking inside large files
- `--brief` is the default for `analyze` and `status`
- `--full` asks for a fuller report/status payload
- `--allow-fallback` lets uncertain repos fall back to generic file-level mode

### Low-level commands

Advanced users can still use:

```bash
python .agents/skills/code-impact-guardian/cig.py init
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --seed <seed>
python .agents/skills/code-impact-guardian/cig.py after-edit --seed <seed> --changed-file <path>
python .agents/skills/code-impact-guardian/cig.py status
```

## Profiles

Real working profiles:

- `python-basic`
- `node-cli`
- `react-vite`

Setup-ready profiles:

- `next-basic`
- `electron-renderer`
- `obsidian-plugin`
- `tauri-frontend`

These profiles only change config defaults, doctor expectations, and suggested
commands.
They do not create new graph systems or new adapter families.

## Supplemental adapters

Stage5+ uses:

```json
{
  "primary_adapter": "auto",
  "supplemental_adapters": ["sql_postgres"]
}
```

Use supplemental adapters when another language should enrich the same graph
and report rather than create a second workflow.

For SQL hints:

- high confidence + unique target -> direct `CALLS`
- high confidence but not confirmed enough -> report hint
- otherwise -> metadata only

## Daily-driver output shape

`analyze` now writes both:

- human report: `.ai/codegraph/reports/impact-<task-id>.md`
- agent report: `.ai/codegraph/reports/impact-<task-id>.json`

Brief mode keeps the console and Markdown shorter by focusing on:

- selected seed
- changed files
- direct callers/callees
- direct tests/rules
- top risks
- next tests
- key evidence paths

## Structured runtime artifacts

Runtime data is written under:

```text
.ai/codegraph/
```

Key files:

- graph DB: `.ai/codegraph/codegraph.db`
- reports: `.ai/codegraph/reports/`
- structured logs: `.ai/codegraph/logs/`
- recent task: `.ai/codegraph/last-task.json`
- handoff card: `.ai/codegraph/handoff/latest.md`

Structured logs include:

- `events.jsonl`
- `errors.jsonl`
- `last-run.json`
- `last-error.json`

Normal failures stay concise.
Tracebacks only print when `--debug` is used.

## Recovery and handoff

Recovery is part of the skill, not just the code.

Read in this order:

1. `.ai/codegraph/logs/last-error.json`
2. `.ai/codegraph/handoff/latest.md`
3. `TROUBLESHOOTING.md`

Use:

```bash
python .agents/skills/code-impact-guardian/cig.py status
```

to see:

- current config/profile/primary/supplemental
- latest build/report/after-edit/analyze/finish status
- latest error
- latest report/test paths
- available seed count
- recent task context
- recommended next step

## What scripts guarantee vs what the agent decides

### Script-guaranteed

- direct-edge-only persistence
- unified graph/report/after-edit flow
- structured runtime logs and last-error snapshots
- recent task persistence
- deterministic single-folder and full-package exports

### Agent-guided

- whether a warning is acceptable for the current task
- whether generic fallback is acceptable when detection is uncertain
- how to narrow scope when multiple seeds are plausible
- how to proceed after a test failure while preserving evidence

## Verification

```bash
python -m unittest tests.test_stage1_workflow -v
python -m unittest tests.test_stage2_workflow -v
python -m unittest tests.test_stage3_workflow -v
python -m unittest tests.test_stage4_workflow -v
python -m unittest tests.test_stage5_workflow -v
python -m unittest tests.test_stage6_workflow -v
python -m unittest tests.test_stage7_workflow -v
python -m unittest tests.test_stage8_workflow -v
```
