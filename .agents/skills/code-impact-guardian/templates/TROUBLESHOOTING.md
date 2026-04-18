# Code Impact Guardian Troubleshooting

This file defines the recovery protocol for agents and humans.

## Doctor failed

1. Read `.ai/codegraph/logs/last-error.json`
2. If the error is config-related, run `setup` again with the right profile and project root.
3. If the error is supplemental-adapter-related, either add the expected files or remove that supplemental adapter from config.
4. Re-run `doctor`, or try `doctor --fix-safe` for safe repairs only

## Detect is uncertain

1. If `detect` falls back to `generic`, decide whether that is acceptable for this repo.
2. If the repo should be Python or TS/JS, set `--profile` or `primary_adapter` explicitly.
3. If the parser still cannot recognize the project, continue with generic fallback instead of fabricating function-level truth.
4. `analyze --allow-fallback` and `finish --allow-fallback` will continue in file-level mode when that is the safest choice.
5. Check `.ai/codegraph/context-resolution.json` to see which source the skill trusted for changed files and seed hints.

## Build failed

1. Check `last-error.json` and `errors.jsonl`
2. Confirm config exists and `project_root` is correct
3. Confirm parser-specific source globs match real files
4. Read `.ai/codegraph/build-decision.json` to see why the run wanted incremental vs full
5. If generated/cache files polluted the diff, ignore them or add them to `.gitignore` before retrying
6. Retry with `--debug` only if the structured error is not enough

## Report failed

1. Confirm the seed exists in `cig.py seeds`
2. Read `.ai/codegraph/seed-candidates.json` for the top ranked candidates
3. If the seed is too broad or stale, rerun `analyze` with `--changed-line <path:line>` or `--patch-file <path>`
4. If needed, start from a file seed before returning to a function/routine seed
5. If multiple candidates were found, use one of the top suggested seeds from the structured error

## After-edit test failed

1. Do not fabricate success
2. Keep `test-results.json` and the report as evidence
3. Read `handoff/latest.md`
4. Read `.ai/codegraph/last-task.json` to recover the last analyze context
5. Read `.ai/codegraph/next-action.json` for the most specific retry recommendation
6. Fix the test command or the code under test
7. Re-run `finish` or `after-edit`

## Coverage unavailable

1. Record the unavailable status and reason
2. Continue the workflow without pretending coverage exists
3. If needed, fix the coverage adapter later as a separate task

## Supplemental adapter failed

1. If the primary adapter still works, continue with the primary graph and record the supplemental failure
2. If the supplemental adapter is required for the task, fix its paths/config first
3. For `sql_postgres`, high-confidence query hints may remain hints until SQL parsing is restored
4. Supplemental adapter failures should degrade to warnings whenever the primary graph is still usable

## Error code guide

- `CONFIG_MISSING`: run `init`
- `INVALID_PROFILE`: choose a supported profile and run `init` again
- `SUPPLEMENTAL_ADAPTER_MISSING`: add the expected files or disable the supplemental adapter
- `SEED_SELECTION_REQUIRED`: rerun `analyze` or `report` with `--changed-line` or an explicit `--seed`
- `TASK_CONTEXT_MISSING`: rerun `analyze`, or provide `--seed` / `--task-id` explicitly when no recent context exists
- `TEST_COMMAND_FAILED`: inspect `test-results.json` and the command output log, then retry after fixing the command or failing code
- `UNEXPECTED_ERROR`: retry with `--debug` and inspect the latest error log
