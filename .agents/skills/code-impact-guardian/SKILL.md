---
name: code-impact-guardian
description: Use this repo-local workflow before changing code. Build or refresh the graph, generate an impact report, edit only after the report exists, then update graph, report, evidence, and tests after the edit.
---

# Code Impact Guardian

This skill is a copyable repository workflow template.

It is not a plugin.
It is not a platform product.
It is not tied to any business repo.

## Fixed workflow

The workflow never changes:

1. build / refresh graph
2. generate impact report
3. read the report
4. edit code
5. update graph / report / evidence / tests

## Stage8 scope

Stage8 keeps the same skill shape and focuses on daily-driver use:

- smarter seed ranking from changed files and changed lines
- brief report/status output by default
- JSON impact reports for agents
- conservative incremental refresh when safe
- better TS/JS + React + SQL day-to-day guidance without new adapter families

TS/JS remains the main app-facing family.
Python remains the stable regression baseline.
`sql_postgres` remains supplemental rather than a second system.

## Durable graph rules

- Nodes: `file`, `function`, `test`, `rule`
- Edges: `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- Persist only direct edges
- Never persist indirect or transitive edges
- Compute transitive impact only during report generation

## Preferred commands

Use these first:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file <path> --changed-line <path:line>
python .agents/skills/code-impact-guardian/cig.py finish --changed-file <path>
```

What they do:

- `setup` initializes config/schema/docs and then runs doctor + detect
- `analyze` builds or reuses the graph, generates a task id when missing, ranks seed candidates, and writes a brief report plus JSON report
- `finish` reuses the latest task context when possible and refreshes report/evidence/tests after the edit

Prefer these flags when needed:

- `--changed-line <path:line>` to improve seed selection
- `--brief` for compact output
- `--full` when you need more detail
- `--allow-fallback` when generic file-level continuation is acceptable

Low-level commands remain available:

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

## Single-folder install promise

Copying only this folder into:

```text
.agents/skills/code-impact-guardian/
```

is now a supported path.

After that, `setup` or `init` must be able to generate:

- `AGENTS.md`
- `.gitignore`
- `.code-impact-guardian/config.json`
- `.code-impact-guardian/schema.sql`
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`
- `CONSUMER_GUIDE.md`

## Generic fallback rule

In generic mode:

- graph stays file-level only
- `seeds` must list file seeds
- `report` must accept file seeds
- `finish` / `after-edit` must still record test and evidence outcomes

Do not pretend generic mode has function-level precision.

## Supplemental adapter rule

Use supplemental adapters when another language should enrich the same graph
and report rather than create a separate workflow.

For SQL hints:

- high confidence + unique target -> direct `CALLS`
- otherwise -> attrs/report hint only

## Recovery protocol

When something fails, do not guess.
Read these in order:

1. `.ai/codegraph/logs/last-error.json`
2. `.ai/codegraph/handoff/latest.md`
3. `TROUBLESHOOTING.md`

The recovery policy is:

- doctor fail -> fix config or environment first, optionally with `doctor --fix-safe`
- detect uncertain -> explicitly choose a profile or allow generic fallback
- build fail -> verify config, project root, and matching globs
- report fail -> rebuild and choose a narrower seed
- finish / after-edit test fail -> preserve evidence, inspect handoff, retry after fixing
- coverage unavailable -> continue honestly, never fabricate
- supplemental adapter fail -> downgrade to primary flow unless the task truly requires the supplemental graph

## Expected outputs

- `.ai/codegraph/codegraph.db`
- `.ai/codegraph/logs/`
- `.ai/codegraph/reports/impact-<task-id>.md`
- `.ai/codegraph/reports/impact-<task-id>.json`
- `.ai/codegraph/test-results.json`
- `.ai/codegraph/last-task.json`
- `.ai/codegraph/handoff/latest.md`

## Evidence policy

- Git evidence is the default.
- GitHub permalink, blame, and compare stay optional.
- If git history is unavailable, record the reason instead of pretending it exists.
- If coverage is unavailable, record the reason instead of fabricating coverage-backed results.
- Local markdown rules remain the main truth source for rule documents.
- Optional external docs may supplement the workflow, but never replace the graph.

## Distribution note

This development repo is not the same thing as the consumer install.

For a distributable artifact use:

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --out path/to/export
python .agents/skills/code-impact-guardian/cig.py export-skill --mode single-folder --out path/to/export
```
