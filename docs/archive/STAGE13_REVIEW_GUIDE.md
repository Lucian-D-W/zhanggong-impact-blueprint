# Stage 13 Review Guide

This file is archived under `docs/archive/` as historical Stage 13 review
material.

It still describes the external Stage 13 package, but it is no longer the best
entry point for the current repository state. For current product behavior, use:

- `README.md`
- `docs/README.md`
- `.agents/skills/zhanggong-impact-blueprint/SKILL.md`

The repository has continued through Stage 14, Stage 15, Stage 15.1, Stage 17,
and Stage 18. Those later stages add adaptive verification, flow scope
governance, repair-loop escalation, final atlas closure, identity unification,
and mutation safety, but they are not the contract described by this Stage 13
review guide.

## What this document is for

Use this guide when reviewing the Stage 13 external bundle specifically:

- `Stage 13.zip`
- top-level folder `Stage 13/`
- root review docs retained for that package contract

## What Stage 13 introduced

- explicit `--test-scope targeted|configured|full`
- `recommend-tests` for executable direct-test commands
- `.ai/codegraph/next-action.json`
- multidimensional trust payloads
- excluded-directory pruning during traversal
- targeted fallback behavior that stays explicit in machine-readable output

## What changed later but is outside this bundle

- Stage 14 added verification budgets, `--shadow-full`, local test-history
  calibration, and runtime integration-pack support
- Stage 15 added flow classes (`bypass`, `lightweight`, `guarded`,
  `risk_sensitive`, `mixed`) plus repair-loop escalation (`L0` through `L3`)
- Stage 15.1 separated mutation safety from flow weight and added working-note
  doc roles plus `assess-mutation`

If you are reviewing the current repository instead of the historical Stage 13
bundle, read the current root/docs entry points first.

## What was hardened after Stage 13 review

- explicit `include_files` can still reach files inside excluded directories
- explicit `graph.exclude_dirs: []` is honored
- `./path` and `.\\path` style repo-relative paths normalize consistently
- failed or skipped tests no longer produce optimistic `next-action` messages
- multi-command targeted runs persist executable command history for audit
- missing `coverage.py` falls back to plain test execution with honest coverage-unavailable reporting

## What reviewers should check first

1. `tests/test_stage13_workflow.py`
2. `tests/test_stage11_workflow.py`
3. `.agents/skills/zhanggong-impact-blueprint/scripts/parser_backends.py`
4. `.agents/skills/zhanggong-impact-blueprint/scripts/after_edit_update.py`
5. `.agents/skills/zhanggong-impact-blueprint/cig.py`
6. `.agents/skills/zhanggong-impact-blueprint/scripts/generate_report.py`
7. `.agents/skills/zhanggong-impact-blueprint/scripts/trust_policy.py`

## Suggested Stage 13 validation commands

```powershell
python -m unittest tests.test_stage11_workflow -v
python -m unittest tests.test_stage13_workflow -v
python -m unittest tests.test_stage9_workflow tests.test_stage10_workflow tests.test_stage11_workflow tests.test_stage13_workflow -v
```

## Packaging intent

The Stage 13 review zip is supposed to be self-consistent and runnable:

- If `tests/` is present, all required fixtures are present too
- `benchmark/` is intentionally included because Stage 9 benchmark-driven tests depend on it
- Temporary runtime state such as `.ai/` and VCS metadata such as `.git/` are intentionally excluded
- Fixture contents under `examples/` and `benchmark/` stay intact even when they contain folders like `dist/`, `build/`, or `.cache/`

