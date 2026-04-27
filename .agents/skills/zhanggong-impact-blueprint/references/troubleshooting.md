# Troubleshooting Reference

## HEALTH_OR_DOCTOR_FAILED

1. Run `health` first to get the compact readiness summary.
2. If deeper repair help is needed, run `doctor --fix-safe`.
3. Then inspect config, project root, rules path, and test command.

## CONTEXT_MISSING

Try one of these:

1. pass `--changed-file`
2. pass `--patch-file`
3. initialize git with `git init`
4. pass `--seed`
5. use `--allow-fallback` only if file-level continuation is acceptable

If the task is documentation-only and the graph has no meaningful source seed,
use `classify-change` to decide whether the edit can stay lightweight instead
of forcing a fake symbol seed.

## SEED_SELECTION_REQUIRED

Re-run with `--seed` using one of the ranked candidates from `seed-candidates.json`.

## TEST_COMMAND_FAILED

Inspect:

- `.ai/codegraph/test-results.json`
- `.ai/codegraph/handoff/latest.md`
- `.ai/codegraph/logs/last-error.json`

Then retry targeted tests first when possible.

## CONTRACT_CONTEXT_LOOKS_WRONG

1. Read `.ai/codegraph/next-action.json`.
2. Check whether the current task was pulled toward an unrelated recent code
   seed.
3. If the task is about API, route, event, SQL, env/config, or IPC contracts,
   inspect `affected_contracts` and `atlas_views`.
4. If the task is documentation-only and those fields are irrelevant, do not
   overfit the edit to stale runtime context.

## Supplemental adapter degraded

If `sql_postgres` fails but the primary adapter succeeds, continue with a warning and review the report/handoff before claiming confidence.
