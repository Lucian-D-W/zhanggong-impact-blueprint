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

Do NOT trigger for:

- comment-only edits outside `docs/rules`
- formatting-only edits that do not change tokens or behavior
- generated/cache/build output files
- README/docs copy edits that do not modify rules, setup commands, or test commands

## Required flow

1. If `.code-impact-guardian/config.json` is missing, run `setup` automatically.
2. Start with `health` when repo readiness is unclear.
3. Before editing, run `analyze`.
4. Read the brief impact result, `.ai/codegraph/next-action.json`, and the verification budget.
5. Only then edit code.
6. After editing, run `finish` with the budget-driven scope from `next-action.json`.
7. If the budget is low-risk, prefer `finish --test-scope targeted`.
8. If targeted mapping is unavailable, trust is low, or dependency/schema risk is elevated, escalate to configured or full tests before handoff.
9. Use `--shadow-full` when you need to calibrate targeted selection against a configured/full shadow run.

## Hard rules

- MUST auto-run `setup` when the repo is not initialized.
- MUST prefer `health -> analyze -> next-action.json -> edit -> finish with budget-driven scope`.
- MUST run `analyze` before changing source, config, schema, or tests.
- MUST NOT edit if the report is missing, empty, or marked `context incomplete`, unless the user explicitly tells you to continue anyway.
- MUST run `finish` after the edit.
- MUST treat the verification budget as the default policy for choosing targeted/configured/full validation.
- MUST explain that `--shadow-full` calibrates targeted verification; it does not make targeted magically complete.
- MUST prefer repo-local integration through `AGENTS.md`, `.ai/codegraph/runtime/*.md`, and `.ai/codegraph/*` state files instead of runtime-private config hooks.
- MUST record unavailable coverage honestly.
- MUST NOT describe `coverage unavailable` as safety.
- MUST NOT describe `tests passed` as safety.
- MUST NOT default every small edit to a full suite.
- MUST NOT claim high confidence when `graph_trust` is low or dependency state is unknown or changed.
- MUST only say which tests passed, which tests were directly affected, and what remains uncovered.

## Preferred commands

Use these high-level commands first:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py health
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py install-integration-pack
python .agents/skills/code-impact-guardian/cig.py finish --test-scope targeted
python .agents/skills/code-impact-guardian/cig.py finish --test-scope targeted --shadow-full
```

Use these when context needs help:

- `--changed-file <path>`
- `--changed-line <path:line>`
- `--patch-file <path>`
- `--allow-fallback`
- `--full`
- `--shadow-full`
- `--debug`

## Decision rules

- If `analyze` selects one high-confidence seed, proceed with that seed.
- If `analyze` returns multiple candidates, do not guess. Ask the user or rerun with `--seed`.
- If context cannot be inferred and fallback is not allowed, stop and surface the recovery steps.
- If fallback is allowed, make it explicit that the report is file-level or context-incomplete.
- If the verification budget is `B2`, prefer targeted tests and keep the loop fast.
- If the verification budget is `B3`, use configured tests even if targeted mapping exists.
- If the verification budget is `B4`, prefer full tests plus dependency/schema review before claiming readiness.
- If targeted passes but the risk is still meaningful, use `--shadow-full` to compare targeted against configured/full and record calibration evidence.

## What to tell the user after analyze

Give a short 1-2 sentence summary:

- selected seed
- direct impact scope
- verification budget and recommended test scope
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
- next-action.json
- verification-policy.json

After `finish`, expect:

- refreshed graph/report/evidence/tests
- budget-aware test scope selection
- optional shadow-full calibration output
- structured logs
- updated handoff
