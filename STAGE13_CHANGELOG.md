# Stage 13 Changelog

This note summarizes the Stage 13 review bundle contents and the follow-up hardening included in the current package.

## Product changes

- Added real-use test scope layering
  - `finish` and `after-edit` now support `--test-scope targeted|configured|full`
  - outputs now distinguish `requested_test_scope` from `effective_test_scope`
  - targeted mode explicitly falls back to configured mode when direct test mapping is unavailable

- Added executable test recommendations
  - `recommend-tests` now converts direct test seeds into runnable commands
  - Python unittest seeds map down to individual test methods
  - TS/JS seeds can fall back to conservative file-level `node --test` execution

- Added next-action guidance
  - `analyze` now emits `.ai/codegraph/next-action.json`
  - payload includes `risk_level`, `can_edit_now`, `must_read_first`, `recommended_test_scope`, `recommended_commands`, `user_message`, and `agent_instruction`

- Added multidimensional trust
  - reports and build decisions now expose `trust.graph`, `trust.parser`, `trust.dependency`, `trust.test_signal`, `trust.coverage`, `trust.context`, and `trust.overall`
  - compatibility with legacy `graph_trust` is preserved

- Improved large-repo traversal performance
  - file discovery now prunes excluded directories instead of recursively walking them first
  - default pruning covers common heavy directories such as `.git`, `.ai`, `node_modules`, `dist`, `build`, `.next`, `.cache`, `coverage`, and virtualenv/cache folders

## Post-review hardening

- Fixed `include_files` being swallowed by pruning
  - explicitly included files inside excluded directories are now still reachable

- Fixed `graph.exclude_dirs: []` being ignored
  - an explicit empty list now really means "do not exclude any directories"

- Fixed repo-relative path normalization edge cases
  - `./path` and `.\\path` style values are normalized consistently for exclude and include matching

- Fixed optimistic `next-action` risk when tests fail
  - failed tests now raise risk instead of allowing a `low` risk result

- Fixed skipped tests being described as passed
  - `next-action` now distinguishes skipped tests from passed tests in its suggestion text

- Fixed multi-command targeted run persistence
  - targeted runs that execute more than one command now persist non-empty command information plus the full command list for audit

## Regression coverage added

- `test_configured_exclude_dirs_allows_explicit_empty_list`
- `test_iter_matching_files_allows_explicit_include_inside_excluded_dir`
- `test_iter_matching_files_normalizes_dot_prefixed_paths`
- `test_finish_targeted_persists_all_mapped_commands`
- `test_next_action_raises_risk_when_tests_fail`
- `test_next_action_skipped_tests_do_not_claim_pass`

## Validation run for this bundle

```powershell
python -m unittest tests.test_stage13_workflow -v
python -m unittest tests.test_stage11_workflow -v
python -m unittest tests.test_parse_test_count_regression tests.test_self_hosting_guard_focus -v
python -m unittest tests.test_stage9_workflow tests.test_stage10_workflow tests.test_stage11_workflow tests.test_stage13_workflow -v
```

All of the commands above were run successfully for the current Stage 13 package.

## Bundle updates

- Review zip name is `Stage 13.zip`
- The zip expands into a single top-level folder named `Stage 13/`
- The bundle includes:
  - `.agents/skills/code-impact-guardian/`
  - `.code-impact-guardian/`
  - `scripts/`
  - `tests/`
  - `examples/`
  - `benchmark/`
  - `README.md`
  - `AGENTS.md`
  - `STAGE13_REVIEW_GUIDE.md`
  - `STAGE13_CHANGELOG.md`
  - `review 0419.txt`
