# Troubleshooting Reference

## DOCTOR_FAILED

Run `doctor --fix-safe`, then inspect config, project root, rules path, and test command.

## CONTEXT_MISSING

Try one of these:

1. pass `--changed-file`
2. pass `--patch-file`
3. initialize git with `git init`
4. pass `--seed`
5. use `--allow-fallback` only if file-level continuation is acceptable

## SEED_SELECTION_REQUIRED

Re-run with `--seed` using one of the ranked candidates from `seed-candidates.json`.

## TEST_COMMAND_FAILED

Inspect:

- `.ai/codegraph/test-results.json`
- `.ai/codegraph/handoff/latest.md`
- `.ai/codegraph/logs/last-error.json`

Then retry targeted tests first when possible.

## Supplemental adapter degraded

If `sql_postgres` fails but the primary adapter succeeds, continue with a warning and review the report/handoff before claiming confidence.

