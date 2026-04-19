# Stage 13 Review Guide

This bundle is meant for external review of the Code Impact Guardian template repository after the Stage 13 "Real-Use Intelligence Layer" work.

## What is included

- Core skill implementation under `.agents/skills/code-impact-guardian/`
- Repo-local configuration under `.code-impact-guardian/`
- Support scripts under `scripts/`
- Workflow and regression tests under `tests/`
- Example consumer fixtures under `examples/`
- Benchmark fixtures under `benchmark/`
- Root documentation in `README.md` and `AGENTS.md`

## What Stage 13 changes

- Adds real test-scope layering through `--test-scope targeted|configured|full`
- Adds `recommend-tests` to convert direct test seeds into executable commands
- Generates `.ai/codegraph/next-action.json` so weaker agents can follow a concrete next step
- Extends trust from a single `graph_trust` value to a multidimensional trust payload
- Prunes large directories during traversal with configurable `graph.exclude_dirs`
- Hardens Stage 13 behavior after review feedback:
  - explicit `include_files` can still reach files inside excluded directories
  - explicit `graph.exclude_dirs: []` is honored
  - `./path` and `.\\path` style repo-relative paths normalize consistently
  - failed or skipped tests no longer produce overly optimistic `next-action` messaging
  - multi-command targeted test runs persist executable command history for audit

## What reviewers should check first

1. `tests/test_stage13_workflow.py`
2. `tests/test_stage11_workflow.py`
3. `.agents/skills/code-impact-guardian/scripts/parser_backends.py`
4. `.agents/skills/code-impact-guardian/scripts/after_edit_update.py`
5. `.agents/skills/code-impact-guardian/cig.py`
6. `.agents/skills/code-impact-guardian/scripts/generate_report.py`
7. `.agents/skills/code-impact-guardian/scripts/trust_policy.py`

## Suggested validation commands

```powershell
python -m unittest tests.test_stage11_workflow -v
python -m unittest tests.test_stage13_workflow -v
python -m unittest tests.test_stage9_workflow tests.test_stage10_workflow tests.test_stage11_workflow tests.test_stage13_workflow -v
```

## Review focus

- `parser_backends.py`
  - verify excluded directory pruning is real pruning, not post-filtering
  - verify explicit include paths still work inside otherwise excluded trees
  - verify repo-relative path normalization is stable

- `after_edit_update.py`
  - verify `recommend-tests` output feeds targeted execution
  - verify targeted multi-command runs persist enough command detail for audit and replay
  - verify fallback from targeted to configured remains explicit

- `cig.py`
  - verify `next-action.json` reflects test status honestly
  - verify failed tests raise risk and skipped tests do not claim success
  - verify requested vs effective test scope are both surfaced

- `generate_report.py` and `trust_policy.py`
  - verify trust remains multidimensional and does not overstate confidence
  - verify dependency or context uncertainty still limits overall trust

## Packaging intent

The review zip is supposed to be self-consistent and runnable:

- If `tests/` is present, all required fixtures are present too
- `benchmark/` is intentionally included because Stage 9 benchmark-driven tests depend on it
- Temporary runtime state such as `.ai/` and VCS metadata such as `.git/` are intentionally excluded
- Fixture contents under `examples/` and `benchmark/` are kept intact even when they contain folders like `dist/`, `build/`, or `.cache/`
