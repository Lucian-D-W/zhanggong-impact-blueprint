---
name: code-impact-guardian
description: Use before editing source files, before editing config/schema/tests, and before behavior changes. If the repo is not initialized, run setup automatically. Run analyze before edit. Run finish after edit. Do not edit if the impact report is missing or empty unless the user explicitly overrides.
---

# Code Impact Guardian

Use this skill as a MUST-run workflow guard for repo-local code changes, but do not force every file through the same heavyweight path.

## Trigger

You MUST use this skill when a task will:

- edit source files
- edit config, schema, or tests
- change behavior
- add or remove functions, routines, rules, or test commands

Do NOT trigger the full guardian flow for:

- ordinary summaries, archives, and historical notes
- non-rule Markdown that does not change commands, rules, tests, config, schema, or source behavior
- diagrams or images such as `.drawio`, `.excalidraw`, `.png`, `.jpg`, `.svg`
- formatting-only edits that do not change tokens or behavior
- generated/cache/build output files

## Flow Scope

### A. Skip full guardian flow

Use bypass flow for:

- ordinary summaries
- ordinary archives
- non-rule Markdown
- flowcharts or images
- documentation that does not change commands, rules, tests, config, schema, or source behavior

Bypass flow means:

- read `next-action.json`
- allow direct editing
- do not require full guardian finish
- do not require tests

### B. Lightweight flow

Use lightweight flow for:

- `AGENTS.md` copy edits
- `SKILL.md` copy edits that do not change command semantics
- `README.md` explanation updates
- runtime docs copy
- handoff template copy
- review guide copy

Lightweight flow means:

- classify the change first
- keep the verification budget at `B1`
- do not default to full tests
- escalate only if command, rule, test, config, or schema semantics changed

### C. Full guardian flow

Use full guardian flow for:

- source code
- tests
- parser, build, trust, report, or after-edit logic
- config, schema, dependency, migration, env, or sql changes
- rule docs
- command behavior
- anything that can change runtime behavior or verification conclusions

## Required flow

1. If `.code-impact-guardian/config.json` is missing, run `setup` automatically.
2. Start with `health` when repo readiness is unclear.
3. Before editing, run `analyze`, unless the change is bypass-class documentation.
4. Read the brief impact result, `.ai/codegraph/next-action.json`, and the verification budget.
5. Only then edit code.
6. After editing, run `finish` with the budget-driven scope from `next-action.json` for guarded or risk-sensitive changes.
7. For bypass-class documentation, do not force `finish`; the change can stop after direct editing.
8. For lightweight changes, use the lightweight recommendation from `next-action.json` and do not jump to full tests by default.
9. If the budget is low-risk, prefer `finish --test-scope targeted`.
10. If targeted mapping is unavailable, trust is low, or dependency/schema risk is elevated, escalate to configured or full tests before handoff.
11. Use `--shadow-full` when you need to calibrate targeted selection against a configured/full shadow run.
12. If the same bug keeps failing, stop local patching and follow the repair-loop escalation guidance.

## Hard rules

- MUST auto-run `setup` when the repo is not initialized.
- MUST prefer `health -> analyze -> next-action.json -> edit -> finish with budget-driven scope`.
- MUST run `analyze` before changing source, config, schema, or tests.
- MUST classify changed files before deciding whether to skip, stay lightweight, or run the full guardian flow.
- MUST NOT edit if the report is missing, empty, or marked `context incomplete`, unless the user explicitly tells you to continue anyway.
- MUST run `finish` after guarded or risk-sensitive edits.
- MUST NOT force `finish` for bypass-class documentation-only edits.
- MUST treat the verification budget as the default policy for choosing targeted/configured/full validation.
- MUST explain that `--shadow-full` calibrates targeted verification; it does not make targeted magically complete.
- MUST prefer repo-local integration through `AGENTS.md`, `.ai/codegraph/runtime/*.md`, and `.ai/codegraph/*` state files instead of runtime-private config hooks.
- MUST record unavailable coverage honestly.
- MUST NOT describe `coverage unavailable` as safety.
- MUST NOT describe `tests passed` as safety.
- MUST NOT default every small edit to a full suite.
- MUST NOT claim high confidence when `graph_trust` is low or dependency state is unknown or changed.
- MUST only say which tests passed, which tests were directly affected, and what remains uncovered.
- MUST NOT keep patching the same local area after repeated failures.
- MUST expand the chain when `repeat_count >= 3`.
- MUST move to full-chain, `B4`, and full tests when `repeat_count >= 4`.

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
- If `change_class` is `bypass`, say that the edit does not affect the runtime graph and skip full guardian flow.
- If `change_class` is `lightweight`, keep the flow light unless command semantics changed.
- If the verification budget is `B2`, prefer targeted tests and keep the loop fast.
- If the verification budget is `B3`, use configured tests even if targeted mapping exists.
- If the verification budget is `B4`, prefer full tests plus dependency/schema review before claiming readiness.
- If targeted passes but the risk is still meaningful, use `--shadow-full` to compare targeted against configured/full and record calibration evidence.
- If `repeat_count >= 3`, stop patching only the last touched file and read the expanded chain first.
- If `repeat_count >= 4`, rerun `analyze --escalation-level L3` and use full tests.

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
- repair-attempt history when tests fail
- loop-breaker report in repeated-failure full-chain mode
