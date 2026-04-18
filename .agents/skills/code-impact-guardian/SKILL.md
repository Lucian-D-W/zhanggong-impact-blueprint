---
name: code-impact-guardian
description: Use before editing source files, before editing config/schema/tests, and before behavior changes. If the repo is not initialized, run setup automatically. Run analyze before edit. Run finish after edit. Do not edit if the impact report is missing or empty unless the user explicitly overrides.
---

# Code Impact Guardian

Use this skill as a MUST-run workflow guard for repo-local code changes.

## Trigger

You MUST use this skill when a task will:

- edit source files
- edit config, schema, or tests
- change behavior
- add or remove functions, routines, rules, or test commands

## Required flow

1. If `.code-impact-guardian/config.json` is missing, run `setup` automatically.
2. Before editing, run `analyze`.
3. Read the brief impact result.
4. Only then edit code.
5. After editing, run `finish`.

## Hard rules

- MUST auto-run `setup` when the repo is not initialized.
- MUST run `analyze` before changing source, config, schema, or tests.
- MUST NOT edit if the report is missing, empty, or marked `context incomplete`, unless the user explicitly tells you to continue anyway.
- MUST run `finish` after the edit.
- MUST record unavailable coverage honestly.
- MUST NOT describe `coverage unavailable` as safety.
- MUST NOT describe `tests passed` as safety.
- MUST only say which tests passed, which tests were directly affected, and what remains uncovered.

## Preferred commands

Use these high-level commands first:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

Use these when context needs help:

- `--changed-file <path>`
- `--changed-line <path:line>`
- `--patch-file <path>`
- `--allow-fallback`
- `--full`
- `--debug`

## Decision rules

- If `analyze` selects one high-confidence seed, proceed with that seed.
- If `analyze` returns multiple candidates, do not guess. Ask the user or rerun with `--seed`.
- If context cannot be inferred and fallback is not allowed, stop and surface the recovery steps.
- If fallback is allowed, make it explicit that the report is file-level or context-incomplete.

## What to tell the user after analyze

Give a short 1-2 sentence summary:

- selected seed
- direct impact scope
- recommended tests
- any uncertainty

If the report is incomplete, say so clearly and do not present it as safe to edit.

## Recovery references

Read these when something fails:

1. `references/operations.md`
2. `references/trust-model.md`
3. `references/troubleshooting.md`
4. `references/supported-modes.md`
5. `.ai/codegraph/logs/last-error.json`
6. `.ai/codegraph/handoff/latest.md`

## Output expectations

After `analyze`, expect:

- brief Markdown report
- JSON report
- context resolution
- seed candidates
- next action

After `finish`, expect:

- refreshed graph/report/evidence/tests
- structured logs
- updated handoff

