---
name: code-impact-guardian
description: Use this repo-local workflow before changing code. Build or refresh the graph, generate an impact report, edit only after the report exists, then update graph, report, evidence, and tests after the edit.
---

# Code Impact Guardian

This skill is a copyable repository workflow template.

It is not a platform product.
It is not a plugin.
It is not tied to any existing business codebase.

## Fixed workflow

1. `build`
2. `report`
3. read the report
4. edit code
5. `after-edit`

The workflow stays fixed even when adapters, profiles, or fixtures change.

## Stage 6 scope

Stage6 keeps the template lightweight and focuses on:

- distribution through `export-skill`
- stronger `init`
- structured runtime logs
- explicit recovery protocol
- `status` and handoff support
- setup-ready profile presets

TS/JS remains the main app-facing adapter family.
Python remains the stable regression baseline.
`sql_postgres` remains supplemental rather than a second system.

## Durable graph rules

- Nodes: `file`, `function`, `test`, `rule`
- Edges: `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- Persist only direct edges
- Never persist indirect or transitive edges
- Compute transitive impact only during report generation

## Preferred commands

Start with:

```bash
python .agents/skills/code-impact-guardian/cig.py init --project-root . --write-agents-md --write-gitignore
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
```

Then:

```bash
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id your-task --seed <seed>
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id your-task --seed <seed> --changed-file <path>
```

Exporting a distribution package:

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --out path/to/exported-skill
```

Status and handoff:

```bash
python .agents/skills/code-impact-guardian/cig.py status
```

## Generic fallback rule

In generic mode:

- graph stays file-level only
- `seeds` must list file seeds
- `report` must accept file seeds
- test and git evidence still need to be recorded

Do not pretend generic mode has function-level precision.

## Supplemental adapter rule

Use supplemental adapters when another language should enrich the same graph
and report rather than create a separate workflow.

For SQL query hints:

- high confidence + unique target -> direct `CALLS`
- otherwise -> attrs/report hint only

## Recovery protocol

When something fails, do not guess.
Read these in order:

1. `.ai/codegraph/logs/last-error.json`
2. `.ai/codegraph/handoff/latest.md`
3. `TROUBLESHOOTING.md`

The recovery policy is:

- doctor fail -> fix config or environment first
- detect uncertain -> explicitly choose a profile or fall back to generic
- build fail -> verify config, project root, and matching globs
- report fail -> rebuild and choose a narrower seed
- after-edit test fail -> preserve evidence, inspect handoff, retry after fixing
- coverage unavailable -> continue honestly, never fabricate
- supplemental adapter fail -> downgrade to primary flow unless the task truly requires the supplemental graph

## Expected outputs

- `.ai/codegraph/codegraph.db`
- `.ai/codegraph/logs/`
- `.ai/codegraph/reports/impact-<task-id>.md`
- `.ai/codegraph/test-results.json`
- `.ai/codegraph/handoff/latest.md`
- function seeds or file seeds from `seeds`

## Evidence policy

- Git evidence is the default.
- GitHub permalink, blame, and compare stay optional.
- If git history is unavailable, record the reason instead of pretending it exists.
- If coverage is unavailable, record the reason instead of fabricating coverage-backed results.
- Local markdown rules remain the main truth source for rule documents.
- Optional external docs may supplement the workflow, but never replace the graph.

## Distribution note

This development repo is not the same thing as the distribution package.
Use `export-skill` to create the minimal package that should be copied into
another repository.
