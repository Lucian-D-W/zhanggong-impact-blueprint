# ZG Impact Blueprint Troubleshooting

This file is a recovery protocol for humans and agents. Start from the current facts, not from defaults.

## First Question: Which Lane?

Run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file <path>
```

- `bypass`: do not force full guardian.
- `lightweight`: keep workflow structure, usually skip tests.
- `full_guardian`: run `analyze` before edit and `finish` after edit.

If a plain doc edit feels over-governed, check whether the file content mentions setup, tests, commands, rules, config, schema, or agent behavior. Those make it lightweight or full guardian depending on impact.

## Setup Feels Too Noisy

Use preview first:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
```

Default setup is minimal. It should only write config, schema, runtime directory, and managed `.gitignore` block.
Use `--full` only when the repo wants onboarding docs and AGENTS integration.

## Analyze Output Feels Too Long

Default `analyze` should be brief. If you need structure, open:

- `.ai/codegraph/summary.json`
- `.ai/codegraph/facts.json`
- `.ai/codegraph/inferences.json`
- `.ai/codegraph/next-action.json`

Facts are observed state. Inferences are uncertainty, fallback, trust, and low-confidence hints.
Do not mix the two when explaining the result.

## Multiple Seeds Appeared

This is not automatically an error.

Read:

- `selected_seed` for the primary view
- `secondary_seeds` for parallel entries
- `seed_coverage.reason` for why the workflow can continue

Only treat `selection_required` as blocking when the output explicitly says the candidate set cannot converge.

## Provider Fell Back

Read `graph_provider`, `provider_effective`, `provider_authority`, `provider_status`, `provider_reason`, `provider_fallback_reason`, and `fallback_provider`.

Valid cases:

- GitNexus missing
- GitNexus stale/unindexed
- path incompatibility
- non-git repo constraints

Continue with internal fallback when the reason is explicit and the lane permits it. Do not let provider fallback silently change test or finish ownership.

If `provider_effective=gitnexus` and `provider_authority=primary`, do not describe the run as internal fallback. Seed/file-level fallback is a separate context-confidence issue, not a GitNexus availability issue.

## Test Command Looks Wrong

Run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
```

Check:

- `selected_test_command`
- `test_command_source`
- `test_command_reason`
- `test_command_candidates`
- `ignored_test_commands`

Priority is repo config > recent successful command > package scripts > provider/adapter fallback > built-in default.
If repo config is being ignored, that is a bug to investigate.

## Tests Passed But No Direct Tests Were Found

Use this wording:

- These tests passed: read `evidence_statement.passed_tests`.
- Directly affected tests identified: read `evidence_statement.directly_affected_tests_found`.
- Evidence weight: `no_regression_signal` means the selected suite did not explode, not that targeted coverage was proven.
- Manual risks: read `evidence_statement.manual_risks`.

Do not say this is fully safe unless targeted/direct coverage or broader verification supports it.

## Broad Discover Was Skipped

Default `finish` verifies the current task. If no current-task test is mapped and the only available command is broad Python `unittest discover`, zhanggong should skip it and explain why.

- Use `--test-command "<current task command>"` when the agent knows the right verification.
- Use `--test-scope full` when you intentionally want broad historical/baseline verification.
- Do not treat broad discover as a substitute for directly affected tests.

## Baseline Is Red

Read:

- `.ai/codegraph/baseline-status.json`
- `.ai/codegraph/test-results.json`
- `.ai/codegraph/final-state.json`

Interpretation:

- `baseline_status = failed` means the repo already had a red baseline.
- `regression_status = no_regression` means the current failure signature matches known baseline reality.
- `regression_status = new_failure` means this run likely introduced or exposed a new failure.
- Passing targeted/smoke tests can coexist with a red historical full suite.

## Trust Looks Low

Trust is axis-based. Read `trust_axes` and `trust_explanation`.

Required axes:

- `graph_freshness`
- `workspace_noise`
- `dependency_confidence`
- `context_confidence`
- `test_signal`
- `overall_trust`

A positive axis such as fresh graph or low workspace noise should not be listed as a downgrade reason. The explanation must name the actual lowering axis.

## Context Missing

Use one of:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <relative-path>
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --patch-file <patch-file>
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --allow-fallback
```

Explicit changed files should beat dirty-worktree inference.

## Error Code Guide

- `CONFIG_MISSING`: run minimal setup.
- `CONTEXT_MISSING`: pass changed-file, patch-file, initialize git, or explicitly allow fallback.
- `SEED_SELECTION_REQUIRED`: the candidate set is too broad; rerun with `--changed-line` or explicit `--seed`.
- `TASK_CONTEXT_MISSING`: rerun `analyze`, or provide `--seed` and `--task-id`.
- `TEST_COMMAND_FAILED`: inspect `test-results.json` and output log.
- `TEST_COMMAND_PREFLIGHT_FAILED`: fix the executable entry point before trusting results.
- `UNEXPECTED_ERROR`: rerun with `--debug` and inspect latest error logs.
