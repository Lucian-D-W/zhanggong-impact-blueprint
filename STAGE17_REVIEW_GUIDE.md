# Stage 17 Review Guide

## Purpose

This guide is the review checklist for the final Stage 17 closure of ZG Impact Blueprint.

The goal is to validate:

- SQLite connections close cleanly
- CLI commands exit cleanly
- atlas views are readable and compressed without deleting full facts
- next-action stays advisory instead of making decisions for the agent
- repeated failures widen reading scope
- release hygiene catches path, privacy, and runtime-artifact leaks

## Test commands

Stage 17:

```bash
python -m unittest tests.test_stage17_workflow -v
```

Stage 16 regression:

```bash
python -m unittest tests.test_stage16_workflow -v
```

Historical regression:

```bash
python -m unittest \
  tests.test_stage15_workflow \
  tests.test_stage15_1_workflow \
  tests.test_stage14_workflow \
  tests.test_stage13_workflow \
  -v
```

Strict warnings:

```bash
python -W error::ResourceWarning -m unittest tests.test_stage16_workflow tests.test_stage17_workflow -v
```

Optional full workflow discover:

```bash
python -m unittest discover -s tests -p "test_stage*_workflow.py" -v
```

## Release check

Run the public-skill hygiene scan:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py release-check --workspace-root . --skill-only
```

## Warnings-as-errors focus

The critical reliability check for Stage 17 is that SQLite warnings are fixed by real resource closure, not by suppressing warnings.

Reviewer expectations:

- no `ResourceWarning: unclosed database`
- no warning filtering to hide the issue
- temp workspaces remain removable after repeated finish loops

## Manual smoke checklist

- Run `export-skill --mode single-folder` and confirm the export does not include `.ai/codegraph` runtime artifacts.
- Run `release-check` on a clean exported skill folder and confirm it passes.
- Add an obvious private-name leak to the exported skill folder and confirm `release-check` fails.
- Add an obvious temp-path leak and confirm `release-check` fails.
- Confirm `analyze` output includes `atlas_views` for contract-heavy changes.
- Confirm `next-action.json` tells the agent how to read the atlas instead of telling it exactly what code change to make.
- Confirm repeated failure produces `loop_atlas_views`.
- Confirm higher retry counts produce `uncertainty` and `stop_local_patching_reason`.

## What reviewers should look for

- `affected_contracts` still contains full facts
- `atlas_views` is a reading layer, not a planner
- `DEPENDS_ON` is clearly marked as low-confidence evidence
- bypass or lightweight doc edits are not dragged into full guardian flow
- `tests_passed` is not described as full safety

