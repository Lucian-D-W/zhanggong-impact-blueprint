# Stage 18.1 Final Acceptance Pack

Status: `accepted candidate`

Release label suggestion: `v0.18.1-rc1`

Stage 18.1 is accepted for the Stage 18 user-feedback blocker scope.
Historical full regression was intentionally out of scope for this hotfix.

Stage 18.1 fixes all known Stage 18 acceptance blockers found in the multi-agent validation pass. Older-stage full regression was intentionally not run in this hotfix round.

## Why 26/26 Was Not Enough

Stage 18 originally reached `26/26 OK` in `tests.test_stage18_workflow`, but that only proved the existing Stage 18 regression suite passed.

It did not prove that real user paths were stable, because the multi-agent validation pass still found failures in:

- real Windows platform values such as `os.name == "nt"`
- terminal encoding edge cases such as `PYTHONIOENCODING=gbk`
- Python repositories using `test/` instead of `tests/`
- repeated baseline/no-regression comparisons with unstable output
- state consistency across `handoff/latest.md`, `test-results.json`, and `next-action.json`

That is why Stage 18 stayed `not accepted` until Stage 18.1 added blocker-focused regressions and reran the scoped evidence.

## Multi-Agent Validation Blockers

The multi-agent validation pass and main-thread reproduction found these 8 Stage 18 acceptance blockers:

1. Windows `.sh` preflight treated `platform="nt"` as non-Windows.
2. GBK/Windows terminal output could turn a passed test run into CLI failure.
3. Python repos with `test/` were detected, but the default command still hardcoded `tests/`.
4. baseline/no_regression comparison was flaky because unstable output leaked into the failure signature.
5. `finish` success could leave stale `Last error` content in `handoff/latest.md`.
6. `SEED_SELECTION_REQUIRED` still produced a success-style `next-action.json` that recommended `finish`.
7. trust explanation could invert axis meaning, for example saying overall trust was low because `workspace_noise` was low.
8. repo-local list-form `test_command` values such as `["node", "--test"]` were treated as unset and could be overridden by package scripts.

## Fixes and Test Coverage

1. Windows `.sh` preflight
- Fix: added `is_windows_platform()` in `.agents/skills/zhanggong-impact-blueprint/scripts/test_command_resolver.py` and routed CLI callers through it.
- Tests:
  - `test_preflight_treats_nt_as_windows`
  - `test_preflight_sh_command_on_nt_fails_not_warns`
  - `test_after_edit_passes_platform_in_a_form_preflight_understands`

2. GBK/Windows output false fail
- Fix: added `safe_json_dumps()`, `print_json()`, and `print_text()` in `.agents/skills/zhanggong-impact-blueprint/scripts/runtime_support.py`; CLI JSON output now uses ASCII-safe terminal rendering.
- Tests:
  - `test_cli_json_output_survives_gbk_encoding_with_unicode_checkmark`

3. Python `test/` default command
- Fix: added `detect_python_test_start_dir()` in `.agents/skills/zhanggong-impact-blueprint/scripts/profiles.py`; resolver/default commands now follow `tests/` first, then `test/`.
- Tests:
  - `test_python_repo_with_singular_test_dir_uses_test_not_tests`
  - `test_python_repo_with_tests_dir_keeps_tests`
  - `test_python_calibrate_test_dirs_match_selected_command`

4. baseline/no_regression flaky signature
- Fix: added `normalize_failure_output()` and `compute_failure_signature()` in `.agents/skills/zhanggong-impact-blueprint/scripts/test_command_resolver.py`; durations, temp paths, line numbers, timestamps, and tmp/hash suffixes are normalized out.
- Tests:
  - `test_failure_signature_ignores_unittest_duration`
  - `test_failure_signature_ignores_absolute_temp_paths`
  - `test_same_baseline_failure_is_no_regression_across_repeated_runs`
  - `test_baseline_regression_status_is_stable_for_10_repeats`

5. handoff stale error after success
- Fix: `.agents/skills/zhanggong-impact-blueprint/scripts/handoff.py` now renders from one `final_state`; successful finish clears `last_error` and sets `last_successful_step=finish`.
- Tests:
  - `test_handoff_clears_previous_error_after_successful_finish`
  - `test_handoff_recent_successful_step_is_finish_after_finish`
  - `test_handoff_tests_passed_matches_test_results_after_fail_then_pass`

6. `SEED_SELECTION_REQUIRED` next-action recommended finish
- Fix: `.agents/skills/zhanggong-impact-blueprint/cig.py` now emits `status=seed_selection_required`, `recommended_test_scope=none`, and only seed-retry commands.
- Tests:
  - `test_seed_selection_required_next_action_does_not_recommend_finish`
  - `test_seed_selection_required_next_action_recommends_seed_retry`
  - `test_seed_selection_required_outputs_consistent_candidate_counts`

7. trust explanation contradiction
- Fix: `.agents/skills/zhanggong-impact-blueprint/scripts/trust_policy.py` and `.agents/skills/zhanggong-impact-blueprint/scripts/generate_report.py` now explain only actual lowering axes and do not reuse stale trust explanations.
- Tests:
  - `test_low_workspace_noise_is_not_used_as_low_trust_reason`
  - `test_trust_explanation_names_actual_lowering_axis`
  - `test_fresh_graph_low_overall_trust_explains_non_freshness_reason`

8. repo config list-form `test_command` not treated as explicit
- Fix: `.agents/skills/zhanggong-impact-blueprint/scripts/test_command_resolver.py` now uses `is_explicit_command()` for string/list config values; non-empty list commands are explicit and beat package scripts.
- Tests:
  - `test_repo_config_list_test_command_is_explicit`
  - `test_repo_config_list_test_command_beats_package_json_script`
  - `test_empty_list_test_command_is_treated_as_unset`

## Final Command Results

Required final commands were rerun for this acceptance pack.

### Stage 18 Suite

Command:

```bash
python -m unittest tests.test_stage18_workflow -v
```

Result:

```text
Ran 26 tests in 25.296s

OK
```

### Stage 18.1 Suite

Command:

```bash
python -m unittest tests.test_stage18_1_workflow -v
```

Result:

```text
Ran 23 tests in 76.776s

OK
```

### Baseline Stability

Command:

```bash
python -m unittest tests.test_stage18_1_workflow.Stage18_1WorkflowTest.test_baseline_regression_status_is_stable_for_10_repeats -v
```

Result:

```text
Ran 1 test in 47.793s

OK
```

This test loops the same baseline-red scenario 10 times and now remains stable.

### GBK Smoke

GBK smoke is covered by `test_cli_json_output_survives_gbk_encoding_with_unicode_checkmark`.

An additional explicit subprocess smoke was also rerun with `PYTHONIOENCODING=gbk`:

- CLI return code: `0`
- `test-results.json.tests_passed`: `true`
- `stderr`: empty
- no `UnicodeEncodeError`

## CLI Smokes

The required CLI smokes were rerun for this pack.

1. `setup --minimal --dry-run`
- Result: `rc=0`
- Evidence: output stayed in preview mode and listed only planned file operations.

2. `calibrate` on node-cli fixture
- Result: `rc=0`
- Selected test command: `npm run test:run`
- Source: `package_json_script:test:run`
- Primary adapter: `tsjs`

3. `analyze` on selection-required fixture
- Result: `rc=1`
- Error: `SEED_SELECTION_REQUIRED`
- `next-action.json.status`: `seed_selection_required`
- Recommended next step: `Choose one seed and rerun analyze.`
- Recommended commands: only `analyze --seed ...`

4. `finish` fail-then-pass fixture
- First finish: `rc=1`
- Second finish: `rc=0`
- `handoff/latest.md` stale `Last error`: `false`

No old-stage full discover or full historical regression was run.

## Real User Path Replay

### A. TS + Python Mixed Repo

Before:

- Python files could steal main adapter choice.
- Verification could drift toward Python defaults instead of the TS/Node entry path.

After:

- Function-level adapter decision with explicit mixed config:
  - `primary_adapter = tsjs`
  - `supplemental_adapters = ["python"]`
- CLI fixture with Node test script:
  - selected test command: `npm run test:run`
  - source: `package_json_script:test:run`
  - finish: `rc=0`
  - detected adapter in `test-results.json`: `tsjs`

Reality check:

- Python no longer steals primary adapter.
- finish does not fall back to Python default verification when the repo is TS-primary.

### B. Node/Vitest Repo

Before:

- node-cli projects could fall back to `node --test` even when `package.json` already had a clearer `test` or `test:run` script.

After:

- selected test command: `npm run test:run`
- source: `package_json_script:test:run`
- `node --test` is not selected when a clearer package script exists
- ignored lower-priority candidates are recorded in the resolver payload

Reality check:

- package scripts now beat the generic adapter fallback for Vitest-style repos.

### C. fail-then-pass Repo

Before:

- `test-results.json` could say passed while `handoff/latest.md` still carried stale failure state.

After:

- first finish: `rc=1`
- second finish: `rc=0`
- `test-results.json.tests_passed = true`
- `handoff/latest.md` does not contain `## Last error`
- handoff line: `Recent successful step: finish ...`

Reality check:

- final user-facing summary now comes from the same final state as `test-results.json`.

## Acceptance Meaning of the 8 Blockers

1. Windows `.sh` preflight
- Reality meaning: Windows users do not have to wait until the last finish step to discover that a `.sh` entry point is not executable there.

2. GBK/Windows output
- Reality meaning: once tests actually pass, terminal encoding limitations do not turn the CLI into a false failure.

3. Python `test/`
- Reality meaning: Python repos that organize tests under `test/` are no longer forced through `tests/`.

4. baseline/no_regression
- Reality meaning: when a repo is already red, the same historical failure is no longer misreported as a new regression from this edit.

5. handoff stale error
- Reality meaning: final human-readable handoff no longer argues with `test-results.json`.

6. `SEED_SELECTION_REQUIRED`
- Reality meaning: if the user has not chosen a seed yet, the tool does not incorrectly tell them to jump straight to `finish`.

7. trust explanation
- Reality meaning: trust output no longer claims that a positive axis such as low workspace noise is the reason trust went down.

8. repo config list command
- Reality meaning: an explicit repo-local command like `["node", "--test"]` is treated as a real user choice and is not overwritten by package script guessing.

## Why Stage 18 Can Move to Accepted Candidate

Stage 18 can now move from `not accepted` to `accepted candidate` because:

- all 8 known Stage 18 acceptance blockers from the multi-agent validation pass were turned into regressions and are now passing
- the original Stage 18 regression suite still passes unchanged
- the flaky baseline comparison now survives the required repeated-run check
- the Windows/GBK and state-consistency issues were verified through both regression tests and CLI smokes

This is enough evidence for the Stage 18 user-feedback blocker scope.

It is not a claim that every historical stage path has been fully revalidated.

## What Was Intentionally Not Tested

The following was intentionally out of scope for Stage 18.1:

- old-stage full regression across all historical stages
- `python -m unittest discover`
- any new feature work beyond the 8 known blockers

Reason:

- this round is a narrow hotfix and acceptance-stabilization pass for Stage 18 user-feedback blockers
- widening to historical full regression would have mixed scopes and delayed blocker closure

## Still-Unverified Range

The still-unverified range is:

- old-stage workflows and regression interactions outside the Stage 18 / Stage 18.1 blocker scope
- any historical tests not covered by `tests.test_stage18_workflow` and `tests.test_stage18_1_workflow`

That remaining uncertainty is expected for this hotfix round and should be handled in a separate Stage 18.2 or backlog item if new user reports appear.

## Release Status

Stage 18.1: `accepted candidate`

This means:

- accepted for the Stage 18 user-feedback blocker scope
- suitable to merge and use for small real-repo trial rollout

This does not mean:

- fully proven across all historical stages
- risk-free across every untouched legacy path
