# Code Impact Guardian

Code Impact Guardian is a lightweight, repo-local skill template for safer code
edits.

It is intentionally shaped as:

- `AGENTS.md`
- one repo-scoped skill
- one SQLite fact store
- one fixed impact report flow
- one unified CLI entry
- one exportable skill package

It is not a plugin.
It is not a platform product.
It is designed to be copied into another repository and then used through
config, profiles, and thin parser backends.

## Fixed workflow

The workflow stays fixed:

1. build / refresh graph
2. generate impact report
3. allow code edits
4. update graph / report / evidence after edit
5. run relevant tests and record outcome

## Support level

### Python

- stable regression baseline
- `file`, `function`, `test`, `rule`
- `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- real `coverage.py` path

### TS/JS family

- `.js`, `.ts`, `.jsx`, `.tsx`
- function declarations
- exported const arrow functions
- React function components
- custom hooks
- minimal class methods
- import / export / re-export / require / module.exports
- node:test and common JS test markers
- real raw V8 coverage path

### SQL/PostgreSQL

- real supplemental adapter in stage5+
- SQL files become `file` nodes
- PostgreSQL routines become `function` nodes
- routine subtype stored in attrs via `sql_kind`
- high-confidence SQL-to-SQL `CALLS`
- high-confidence SQL test `COVERS`
- test outcome recorded even when coverage is unavailable

### Generic fallback

- file-level only
- still supports build / report / after-edit / test outcome
- never pretends to have function-level precision

## Stage6 focus

Stage6 does not widen the language matrix.
Instead it turns the existing system into a more reusable skill template:

- exportable minimal skill package
- stronger `init`
- unified structured event and error logging
- explicit recovery protocol
- `status` and handoff support for agent takeover
- setup-ready profile presets for more real TS/JS repo shapes

## Development repo vs exported skill package

This repository is the development source.

It contains:

- examples
- tests
- implementation history
- working fixtures for stage1 through stage6

The exported skill package is the distribution artifact.

It contains only the minimum copyable pieces:

- `AGENTS.template.md`
- `.agents/skills/code-impact-guardian/`
- `.code-impact-guardian/config.template.json`
- `.code-impact-guardian/schema.sql`
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`

The exported package intentionally excludes:

- `.git`
- `.ai`
- `tests`
- `examples`
- `dist`
- `__pycache__`
- old review zips

## Exporting the skill

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --out path/to/exported-skill
```

## Copying to a new project

1. Export the skill package.
2. Copy the exported package contents into the target repo.
3. Run `init`.

Shortest path:

```bash
python .agents/skills/code-impact-guardian/cig.py init --project-root . --write-agents-md --write-gitignore
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id my-task --seed <seed>
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id my-task --seed <seed> --changed-file <path>
```

### Python repo

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile python-basic --project-root . --write-agents-md --write-gitignore
```

### TS/JS repo

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --project-root . --write-agents-md --write-gitignore
```

### TS/JS + PostgreSQL repo

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile react-vite --with sql-postgres --project-root . --write-agents-md --write-gitignore
```

## Primary and supplemental adapters

Stage5+ uses:

```json
{
  "primary_adapter": "auto",
  "supplemental_adapters": ["sql_postgres"]
}
```

Use a supplemental adapter when another language should enrich the same graph
and report rather than become a second workflow.

## Profiles

Real working profiles:

- `python-basic`
- `node-cli`
- `react-vite`

Setup-ready profiles in stage6:

- `next-basic`
- `electron-renderer`
- `obsidian-plugin`
- `tauri-frontend`

These setup-ready profiles do not create new graph systems.
They improve:

- init defaults
- doctor expectations
- default rule globs
- recommended test-command shape

## Seeds and report behavior

`seeds` exposes graph-derived candidates and metadata.

`report` shows:

- adapter/profile context
- seed definition metadata
- direct callers / callees / tests / rules
- transitive paths computed only at report time
- hint data where a relation is useful but not strong enough to become graph truth

### Hint vs real edge

For cross-language SQL hints:

- high confidence + unique target -> direct `CALLS`
- otherwise -> attrs/report hint only

This keeps the graph clean and direct-edge-only.

## Structured runtime logs

All CLI commands now write unified logs under:

```text
.ai/codegraph/logs/
```

Files:

- `events.jsonl`
- `errors.jsonl`
- `last-run.json`
- `last-error.json`

Each event/error carries machine-readable fields such as:

- `timestamp`
- `command`
- `workspace_root`
- `project_root`
- `profile`
- `primary_adapter`
- `supplemental_adapters`
- `task_id`
- `seed`
- `status`
- `output_paths`
- `warning_count`
- `error_code`
- `retryable`
- `suggested_next_step`

Normal failures stay concise on the terminal.
Tracebacks are only printed when `--debug` is used.

## Status and handoff

Use:

```bash
python .agents/skills/code-impact-guardian/cig.py status
```

It reports:

- current config path
- current profile / primary / supplemental
- latest build / report / after-edit status
- latest error summary
- latest report path
- latest test-results path
- available seed count
- whether an unhandled error is present

Agent handoff is written to:

```text
.ai/codegraph/handoff/latest.md
```

It includes:

- current command/task
- current phase
- latest failure point
- latest report/test artifact paths
- the next action another agent should take

## Troubleshooting and recovery

The recovery protocol is part of the skill, not just an implementation detail.

Read:

- `TROUBLESHOOTING.md`
- `.ai/codegraph/logs/last-error.json`
- `.ai/codegraph/handoff/latest.md`

Examples:

- `CONFIG_MISSING`: run `init`
- `INVALID_PROFILE`: choose a supported profile and rerun `init`
- `SUPPLEMENTAL_ADAPTER_MISSING`: add the expected files or disable the supplemental adapter
- `TEST_COMMAND_FAILED`: inspect test output, fix the command or failing code, then rerun `after-edit`

## What the scripts guarantee vs what the agent decides

### Script-guaranteed

- direct-edge-only persistence
- build / report / after-edit flow
- SQLite schema and process tables
- structured logs and last-error snapshots
- handoff artifact generation
- deterministic export package shape

### Agent-guided

- whether to fall back to generic when detection is uncertain
- whether a warning can be accepted for the current task
- how to narrow a seed when report scope is too broad
- how to proceed after a test failure while preserving evidence

## Verification

```bash
python -m unittest tests.test_stage1_workflow -v
python -m unittest tests.test_stage2_workflow -v
python -m unittest tests.test_stage3_workflow -v
python -m unittest tests.test_stage4_workflow -v
python -m unittest tests.test_stage5_workflow -v
python -m unittest tests.test_stage6_workflow -v
```
