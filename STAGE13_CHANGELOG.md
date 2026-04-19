# Stage 13 Changelog

This file is kept at the repository root for Stage 13 review-bundle
compatibility.

It summarizes what the Stage 13 package contained and what was hardened before
that package was considered reviewable. For the current repository state, use:

- `README.md`
- `docs/README.md`

The repository now includes later Stage 14 and Stage 15 work. This changelog
is intentionally Stage 13-scoped and is retained only because the external
Stage 13 review package still expects it at the repository root.

## Stage 13 product changes

- Added real-use test scope layering
  - `finish` and `after-edit` support `--test-scope targeted|configured|full`
  - outputs distinguish `requested_test_scope` from `effective_test_scope`
  - targeted mode falls back to configured mode when direct test mapping is unavailable

- Added executable test recommendations
  - `recommend-tests` converts direct test seeds into runnable commands
  - Python unittest seeds map to individual test methods
  - TS/JS seeds can fall back to conservative file-level `node --test` execution

- Added next-action guidance
  - `analyze` emits `.ai/codegraph/next-action.json`
  - payload includes `risk_level`, `can_edit_now`, `must_read_first`, `recommended_test_scope`, `recommended_commands`, `user_message`, and `agent_instruction`

- Added multidimensional trust
  - reports and build decisions expose `trust.graph`, `trust.parser`, `trust.dependency`, `trust.test_signal`, `trust.coverage`, `trust.context`, and `trust.overall`
  - compatibility with legacy `graph_trust` is preserved

- Improved large-repo traversal performance
  - file discovery prunes excluded directories instead of recursively walking them first
  - default pruning covers common heavy directories such as `.git`, `.ai`, `node_modules`, `dist`, `build`, `.next`, `.cache`, `coverage`, and common cache folders

## Stage 13 post-review hardening

- fixed include-files inside excluded directories being swallowed by pruning
- fixed explicit `graph.exclude_dirs: []` being ignored
- fixed repo-relative path normalization edge cases
- fixed optimistic `next-action` risk when tests fail
- fixed skipped tests being described as passed
- fixed multi-command targeted run persistence
- fixed missing `coverage.py` to fall back to plain test execution with explicit `coverage_status=unavailable`

## Related later stages

- Stage 14 added adaptive verification budgets, `--shadow-full`, local
  calibration/history, and runtime integration-pack support
- Stage 15 added flow scope governance, non-runtime bypass/lightweight paths,
  repair-loop escalation, and expanded-chain diagnostics

## Regression coverage added for Stage 13

- `test_configured_exclude_dirs_allows_explicit_empty_list`
- `test_iter_matching_files_allows_explicit_include_inside_excluded_dir`
- `test_iter_matching_files_normalizes_dot_prefixed_paths`
- `test_matches_any_normalizes_dot_prefixed_relative_path`
- `test_finish_targeted_persists_all_mapped_commands`
- `test_next_action_raises_risk_when_tests_fail`
- `test_next_action_skipped_tests_do_not_claim_pass`
- `test_coveragepy_missing_runs_plain_tests_and_marks_coverage_unavailable`

## Stage 13 validation commands

```powershell
python -m unittest tests.test_stage13_workflow -v
python -m unittest tests.test_stage11_workflow -v
python -m unittest tests.test_parse_test_count_regression tests.test_self_hosting_guard_focus -v
python -m unittest tests.test_stage9_workflow tests.test_stage10_workflow tests.test_stage11_workflow tests.test_stage13_workflow -v
```

## Bundle notes

- review zip name: `Stage 13.zip`
- top-level folder: `Stage 13/`
- root compatibility docs retained:
  - `STAGE13_REVIEW_GUIDE.md`
  - `STAGE13_CHANGELOG.md`
