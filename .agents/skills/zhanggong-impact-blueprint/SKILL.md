---
name: zhanggong-impact-blueprint
description: GitNexus-first repo-local impact workflow for code changes. Use for source, tests, config/schema, commands, rules, or behavior changes; use lightweight or bypass lanes for non-runtime docs so zhanggong stays low-friction.
---

# ZG Impact Blueprint

Use this skill as a repo-local workflow harness, not as a universal checkpoint.
Stage 21 keeps the useful spine of `setup -> health -> analyze -> finish`, but makes the default experience lower-friction and more explicit about facts, inferences, and lane choice.

## Core Model

- `zhanggong` is the user-facing workflow owner.
- `GitNexus` is the default primary graph fact source when ready.
- Provider status is evidence, not workflow ownership: GitNexus supplies graph facts; zhanggong owns lane, seed, test, finish, and handoff.
- Internal fallback is valid only when GitNexus is missing, stale, unindexed, path-incompatible, or explicitly disabled; it must say why it took over.
- Do not run bare `gitnexus analyze` as the normal path. Use zhanggong so GitNexus side effects are suppressed and provider authority is recorded.
- Latest repo facts beat defaults: repo config > recent successful facts > package scripts > provider/adapter fallback > built-in defaults.

## Workflow Lanes

Use the smallest lane that honestly fits the task.

| Lane | Use For | Examples | Required Flow |
| --- | --- | --- | --- |
| bypass | Non-runtime, non-rule, non-agent-behavior edits | archive notes, ordinary docs copy, diagrams, review prose | no full guardian flow |
| lightweight | Agent/workflow/process docs that do not directly change code behavior | `AGENTS.md`, `SKILL.md`, quickstart/troubleshooting, templates | classify/read summary; tests usually none |
| full guardian | Code or behavior-affecting changes | source, tests, config, schema, SQL, env, dependencies, rules, commands | analyze before edit, finish after edit |

When unsure, run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file <path>
```

Read `workflow_lane`, `lane_explanation`, `verification_budget`, and `recommended_test_scope`.

## Setup Protocol

Default setup is minimal. It should not flood a real repo with onboarding files.

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root .
```

Minimal setup writes only runtime essentials. Use `--full` only when the repo explicitly wants docs/templates/AGENTS integration.

## Daily Full Guardian Flow

Use this for source, tests, config, schema, rules, command behavior, dependencies, env, SQL, or docs that change runtime/setup/command behavior.

1. Run `health` when repo readiness is unclear.
2. Run `calibrate` when adapter, provider, baseline, or test command choice is unclear.
3. Run `analyze --workspace-root . --changed-file <path>` before editing.
4. Read the brief terminal output first.
5. Read `.ai/codegraph/next-action.json` when the agent needs machine-readable guidance.
6. Read `affected_contracts` and `atlas_views` when the change may cross API, route, event, IPC, SQL, config, or env surfaces.
7. Edit.
8. Run `finish` with the recommended scope.

## Output Contract

`analyze` defaults to a short brief. Full evidence lands on disk:

- `.ai/codegraph/summary.json` for first-glance decision
- `.ai/codegraph/facts.json` for observed facts only
- `.ai/codegraph/inferences.json` for uncertainty, fallback, and trust interpretation
- `.ai/codegraph/next-action.json` for the agent control plane
- `.ai/codegraph/reports/*.json` and `.md` for impact details
- `.ai/codegraph/final-state.json` after `finish`
- `.ai/codegraph/handoff/latest.md` after `finish`

High-confidence facts and low-confidence hints must not be presented as the same kind of evidence.

## Multi-Entry Tasks

Multi-entry changes should usually continue instead of hard-stopping.

- `selected_seed` is the primary view.
- `secondary_seeds` are parallel entry points to keep visible.
- `selection_required` is reserved for cases where the candidate set is too broad to converge honestly.

## Trust Protocol

Trust is explained across axes:

- `graph_freshness`
- `workspace_noise`
- `dependency_confidence`
- `context_confidence`
- `test_signal`
- `overall_trust`

A positive axis must not be used as a downgrade reason. If overall trust is low, name the axis that actually lowered it.

## Test Language

Tests passed is evidence, not proof.
Default verification is current-task verification, not historical-suite archaeology.
If zhanggong cannot map a current-task test and the only available command is a broad Python `unittest discover`,
it should skip that command by default and explain that broad discover is reserved for `--test-scope full` or explicit `--test-command`.
When no directly affected tests are identified but a configured/full/smoke suite passes, say:

- which tests passed
- whether directly affected tests were found
- whether the evidence is closer to no-regression signal or targeted coverage
- what still needs human confirmation

Baseline red is historical repo reality unless the current failure signature proves a new regression.

## Preferred Commands

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file <path>
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

## Need More Detail?

Read these reference files only when needed:

- `references/STAGE21_WORKFLOW_REFOCUS.md`
- `references/WORKFLOW_MATRIX.md`
- `references/CLI_OUTPUT_CONTRACT.md`
- `references/ROLLOUT_CHECKLIST.md`
- `references/operations.md`
- `references/troubleshooting.md`
- `references/trust-model.md`
- `references/supported-modes.md`
