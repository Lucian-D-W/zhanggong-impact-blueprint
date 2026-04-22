---
name: zhanggong-impact-blueprint
description: Use before editing source files, config/schema/tests, or behavior. Run analyze before edit and finish after edit. Prefer repo-local config and explicit context over defaults, and keep handoff/test state aligned from one final state.
---

# ZG Impact Blueprint

ZG Impact Blueprint is the final repo-local impact atlas plus verification guardrail for this repository.

It is not a platform. It does not use LSP, runtime trace or profiling, embedding or semantic search, or CI history learning. It stays repo-local, lightweight, explainable, and reversible.

Its core job is:

- show impact before editing
- leave structured evidence after editing
- help recovery when verification fails
- widen the reading surface when the same failure repeats
- present architecture contracts as part of the working atlas, not as an auto-planner

The system only does three things:

- make graph facts visible
- mark uncertainty clearly
- keep resources, logs, and release packaging clean

## Trigger

You MUST use this skill when a task will:

- edit source files
- edit config, schema, or tests
- change behavior
- add or remove functions, routines, rules, or test commands

Do NOT trigger the full workflow for:

- ordinary summaries, archives, and historical notes
- non-rule Markdown that does not change commands, rules, tests, config, schema, or source behavior
- diagrams or images such as `.drawio`, `.excalidraw`, `.png`, `.jpg`, `.svg`
- formatting-only edits that do not change tokens or behavior
- generated/cache/build output files

## Flow Scope

### A. Skip full workflow

Use bypass flow for:

- ordinary summaries
- ordinary archives
- non-rule Markdown
- flowcharts or images
- documentation that does not change commands, rules, tests, config, schema, or source behavior

Bypass flow means:

- read `next-action.json`
- allow direct editing
- do not require `finish`
- do not require tests

### B. Lightweight flow

Use lightweight flow for:

- `AGENTS.md` copy edits
- `SKILL.md` copy edits that do not change command semantics
- `README.md` explanation updates
- declared working notes defined by repo-local `doc_roles`
- heuristic working notes such as journals, logs, or progress notes that record
  status rather than changing runtime behavior
- runtime docs copy
- handoff template copy
- review guide copy

Lightweight flow means:

- classify the change first
- keep the verification budget at `B1`
- do not default to full tests
- escalate only if command, rule, test, config, or schema semantics changed

### C. Full workflow

Use the full workflow for:

- source code
- tests
- parser, build, trust, report, or after-edit logic
- config, schema, dependency, migration, env, or sql changes
- rule docs
- command behavior
- anything that can change runtime behavior or verification conclusions

For source, tests, config, schema, rules, dependency, API, route, event, IPC, SQL, env, or config surface changes, do not stop at function callers and callees. Read `affected_contracts`, `atlas_views`, and any `uncertainty` view as part of the construction atlas for the change.

## Mutation safety

Flow weight and mutation safety are separate checks.

Use `assess-mutation` before:

- moving protected docs
- archiving protected docs
- deleting files
- permanently deleting anything

Mutation rules:

- ordinary edit safety is decided by `change_class`
- move/archive safety is decided by protected-doc rules
- delete actions default to recycle bin or trash only
- permanent delete always requires strict user approval

## Required flow

1. If `.zhanggong-impact-blueprint/config.json` is missing, run `setup` automatically.
2. Start with `health` when repo readiness is unclear.
3. Before editing, run `analyze`, unless the change is bypass-class documentation.
4. Read the brief impact result, `.ai/codegraph/next-action.json`, and the verification budget.
5. Review `affected_contracts` and `atlas_views` before assuming the impact is function-only.
6. Only then edit code.
7. After editing, run `finish` with the budget-driven scope from `next-action.json` for guarded or risk-sensitive changes.
8. For bypass-class documentation, do not force `finish`; the change can stop after direct editing.
9. For lightweight changes, use the lightweight recommendation from `next-action.json` and do not jump to full tests by default.
10. If the budget is low-risk, prefer `finish --test-scope targeted`.
11. If targeted mapping is unavailable, trust is low, or dependency/schema risk is elevated, escalate to configured or full tests before handoff.
12. Use `--shadow-full` when you need to calibrate targeted selection against a configured/full shadow run.
13. If the same bug keeps failing, stop local patching and read `loop_atlas_views` before patching again.

## Hard rules

- MUST auto-run `setup` when the repo is not initialized.
- MUST prefer `health -> analyze -> next-action.json -> edit -> finish with budget-driven scope`.
- MUST run `analyze` before changing source, config, schema, or tests.
- MUST classify changed files before deciding whether to skip, stay lightweight, or run the full workflow.
- MUST treat working notes as lightweight unless they truly change command, rule, test, config, or schema semantics.
- MUST assess move/archive/delete risk separately from change classification.
- MUST NOT edit if the report is missing, empty, or marked `context incomplete`, unless the user explicitly tells you to continue anyway.
- MUST run `finish` after guarded or risk-sensitive edits.
- MUST NOT force `finish` for bypass-class documentation-only edits.
- MUST treat the verification budget as the default policy for choosing targeted/configured/full validation.
- MUST treat architecture contracts as first-class impact evidence, not optional decoration.
- MUST inspect `affected_contracts` when API, route, event, table, config, env, or IPC names or payloads change.
- MUST inspect `atlas_views` for API, route, event, IPC, SQL, env, and config surface changes.
- MUST use `DEPENDS_ON` only as a low-confidence fallback for real dependency facts whose precise relationship is uncertain.
- MUST NOT describe low-confidence contract matches as high-confidence architectural truth.
- MUST keep the contract graph repo-local and lightweight; do not introduce LSP, embedding, or runtime tracing assumptions.
- MUST explain that `--shadow-full` calibrates targeted verification; it does not make targeted magically complete.
- MUST prefer repo-local integration through `AGENTS.md`, `.ai/codegraph/runtime/*.md`, and `.ai/codegraph/*` state files instead of runtime-private config hooks.
- MUST record unavailable coverage honestly.
- MUST NOT describe `coverage unavailable` as safety.
- MUST NOT describe `tests passed` as safety.
- MUST NOT describe `tests_passed` as fully safe.
- MUST NOT default every small edit to a full suite.
- MUST NOT claim high confidence when `graph_trust` is low or dependency state is unknown or changed.
- MUST only say which tests passed, which tests were directly affected, and what remains uncovered.
- MUST NOT keep patching the same local area after repeated failures.
- MUST expand the reading surface when `repeat_count >= 3`.
- MUST move to full-chain, `B4`, and full tests when `repeat_count >= 4`.
- MUST move deletions to recycle bin or trash by default.
- MUST NOT permanently delete without explicit, strict user approval.

## Preferred commands

Use these high-level commands first:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py health
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file path/to/file
python .agents/skills/zhanggong-impact-blueprint/cig.py assess-mutation --workspace-root . --path path/to/file --action move
python .agents/skills/zhanggong-impact-blueprint/cig.py build --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze
python .agents/skills/zhanggong-impact-blueprint/cig.py install-integration-pack
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --test-scope targeted
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --test-scope targeted --shadow-full
```

Use these when context needs help:

- `--changed-file <path>`
- `--changed-line <path:line>`
- `--patch-file <path>`
- `--allow-fallback`
- `--full`
- `--shadow-full`
- `--debug`
- `--json`
- `--full-json`

## Repo reality calibration rules

- `primary_adapter=auto`, empty, null, or missing is treated as unset
- if `primary_adapter` is unset and `language_adapter` is concrete, `language_adapter` wins
- if both are unset, auto-detect can choose a main adapter and optional `supplemental_adapters`
- `primary_adapter` decides the main graph, default seed bias, finish verification, and test command choice
- `supplemental_adapters` only add indexing coverage; they do not take over the repo
- for test command selection, keep this order:
  repo config > recent successful command > package script > profile fallback > adapter default
- `setup` defaults to `minimal`; use `--full` only when you explicitly want docs and AGENTS managed output
- `analyze` defaults to brief terminal output; use `--json` or `--full-json` for machine consumption
- use `baseline` plus `regression_status` when the repo is not historically all-green

## Real repo priority principles

- user-explicit config wins over default profile behavior
- explicit `--changed-file` wins over dirty worktree noise
- `test-results.json`, `handoff/latest.md`, and `next-action.json` must come from the same final state
- do not enter `finish` while seed selection is still unresolved
- terminal output must be safe for the active console encoding and must not turn a passed test run into a fake CLI failure

## Decision rules

- If `analyze` selects one high-confidence seed, proceed with that seed.
- If `analyze` returns multiple candidates, do not guess. Ask the user or rerun with `--seed`.
- If context cannot be inferred and fallback is not allowed, stop and surface the recovery steps.
- If fallback is allowed, make it explicit that the report is file-level or context-incomplete.
- If `change_class` is `bypass`, say that the edit does not affect the runtime graph and skip the full workflow.
- If `change_class` is `lightweight`, keep the flow light unless command semantics changed.
- If `doc_role` is `working_note`, do not promote it to guarded just because it mentions verification vocabulary.
- If the action is move/archive/delete, use mutation safety instead of pretending change classification alone is enough.
- If the verification budget is `B2`, prefer targeted tests and keep the loop fast.
- If the verification budget is `B3`, use configured tests even if targeted mapping exists.
- If the verification budget is `B4`, prefer full tests plus dependency/schema review before claiming readiness.
- If a contract match is low-confidence, acknowledge it as partial evidence and avoid strong declarations.
- If an API, route, event, table, env/config key, or IPC channel changed, do not stop at function `CALLS`; review the relevant `atlas_views` too.
- If targeted passes but the risk is still meaningful, use `--shadow-full` to compare targeted against configured/full and record calibration evidence.
- If `repeat_count >= 3`, stop patching only the last touched file and read `loop_atlas_views` first.
- If `repeat_count >= 4`, rerun `analyze --escalation-level L3` and use full tests.

## Agent Atlas reading order

Recommended reading order:

1. read `change_class` and `verification_budget`
2. read `affected_contracts`
3. read `atlas_views`
4. read the `uncertainty` view
5. edit only after reviewing the relevant view
6. finish with the recommended scope
7. if repeated failure happens, read `loop_atlas_views` before patching again

`affected_contracts` keeps the full fact list.

`atlas_views` is the reading layer:

- `bilateral_contract`: sender and handler, emit and handle, register and invoke, backend endpoint and frontend caller
- `page_flow`: route to component to child component to prop or flow
- `data_flow`: endpoint or function to query or mutation to table to migration or tests
- `config_surface`: env var or config key to reader path to affected flow
- `uncertainty`: fallback evidence such as `DEPENDS_ON`, dynamic names, low-confidence matches, or file-level fallback

`atlas_views` does not decide for the agent. It only reorganizes existing graph facts into readable booklets.

## What to tell the user after analyze

Give a short 1-2 sentence summary:

- selected seed
- direct impact scope
- affected contracts or architecture chains when present
- verification budget and recommended test scope
- recommended tests
- any uncertainty

If the report is incomplete, say so clearly and do not present it as safe to edit.

If `atlas_views` contains a bilateral contract, tell the user to review both sides together.

If `atlas_views` contains page or data flow views, tell the user to review the whole chain together.

If `uncertainty` is present, say clearly that those entries are hints, not proof.

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
- `atlas_views`
- `atlas_summary`

After `finish`, expect:

- refreshed graph/report/evidence/tests
- budget-aware test scope selection
- optional shadow-full calibration output
- structured logs
- updated handoff
- repair-attempt history when tests fail
- loop-breaker report in repeated-failure full-chain mode
- `loop_atlas_views` when repeated failures widen the reading surface

