# Code Impact Guardian Troubleshooting

This file defines the recovery protocol for agents and humans.

## Doctor failed

1. Read `.ai/codegraph/logs/last-error.json`
2. If the error is config-related, run `init` again with the right profile and project root.
3. If the error is supplemental-adapter-related, either add the expected files or remove that supplemental adapter from config.
4. Re-run `doctor`

## Detect is uncertain

1. If `detect` falls back to `generic`, decide whether that is acceptable for this repo.
2. If the repo should be Python or TS/JS, set `--profile` or `primary_adapter` explicitly.
3. If the parser still cannot recognize the project, continue with generic fallback instead of fabricating function-level truth.

## Build failed

1. Check `last-error.json` and `errors.jsonl`
2. Confirm config exists and `project_root` is correct
3. Confirm parser-specific source globs match real files
4. Retry with `--debug` only if the structured error is not enough

## Report failed

1. Confirm the seed exists in `cig.py seeds`
2. If the seed is too broad or stale, rebuild and pick a narrower seed
3. If needed, start from a file seed before returning to a function seed

## After-edit test failed

1. Do not fabricate success
2. Keep `test-results.json` and the report as evidence
3. Read `handoff/latest.md`
4. Fix the test command or the code under test
5. Re-run `after-edit`

## Coverage unavailable

1. Record the unavailable status and reason
2. Continue the workflow without pretending coverage exists
3. If needed, fix the coverage adapter later as a separate task

## Supplemental adapter failed

1. If the primary adapter still works, continue with the primary graph and record the supplemental failure
2. If the supplemental adapter is required for the task, fix its paths/config first
3. For `sql_postgres`, high-confidence query hints may remain hints until SQL parsing is restored

## Error code guide

- `CONFIG_MISSING`: run `init`
- `INVALID_PROFILE`: choose a supported profile and run `init` again
- `SUPPLEMENTAL_ADAPTER_MISSING`: add the expected files or disable the supplemental adapter
- `TEST_COMMAND_FAILED`: inspect `test-results.json` and the command output log, then retry after fixing the command or failing code
- `UNEXPECTED_ERROR`: retry with `--debug` and inspect the latest error log
