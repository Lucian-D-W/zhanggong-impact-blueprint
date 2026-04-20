# Code Impact Guardian Consumer Guide

This guide is for repos that copied only:

`./.agents/skills/code-impact-guardian/`

## Fast path

1. Run setup:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
```

2. Generate a report for the file you plan to edit:

```bash
python .agents/skills/code-impact-guardian/cig.py analyze
```

3. Edit the code.

4. Refresh graph, report, evidence, and tests:

```bash
python .agents/skills/code-impact-guardian/cig.py finish
```

What these commands try to do for you:

- `setup` writes the minimum repo-local files and checks the environment
- `analyze` tries to infer the changed scope before you edit
- `analyze` can also surface `affected_contracts` and `architecture_chains`
  when the change reaches beyond function-level impact
- `finish` refreshes the graph/report and records the test signal honestly

## Python

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile python-basic --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

## TS/JS

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

## TS/JS + PostgreSQL

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --with sql-postgres --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

## Daily-use tips

- Prefer `analyze` over low-level `report`; it infers changed files and ranks seeds for you.
- Add `--changed-line <path:line>` only when the inferred top candidates are still too broad.
- Add `--patch-file <path>` when your editor or agent already has a patch artifact.
- Default output is `brief`; add `--full` only when you need more.
- Read `affected_contracts` and `architecture_chains` before treating API,
  route, event, table, config/env, or IPC changes as function-only edits.
- Treat `DEPENDS_ON` as bounded fallback evidence when the precise relationship
  type is uncertain.
- Check `.ai/codegraph/reports/impact-<task-id>.json` when another agent needs machine-readable context.
- Read `.ai/codegraph/build-decision.json` when you need to understand why the run trusted incremental vs full rebuild.
- `tests passed` does not mean the change is proven safe; always read `report_completeness`, `graph_trust`, and `test_signal` together.
- If `analyze` says the context is incomplete, do not keep editing as if the report were complete.

## When you normally do not trigger the workflow

- comment-only edits outside `docs/rules`
- formatting-only edits that do not change tokens or behavior
- generated/cache/build output files
- README/docs copy edits that do not modify rules, setup commands, or test commands

## When you still need to pass `--seed`

Most of the time you should not need it. You normally only pass `--seed` when:

- multiple functions or routines in the same diff remain genuinely ambiguous
- the repo is not using git and you did not provide `--changed-file` or `--patch-file`
- you intentionally want to analyze a specific function/routine instead of the current diff

If `analyze` cannot safely choose, it will only show the top few ranked
candidates and ask you to be explicit.

## Where to look on failure

- Status: run `python .agents/skills/code-impact-guardian/cig.py status`
- Health: run `python .agents/skills/code-impact-guardian/cig.py health --workspace-root .`
- Handoff: `.ai/codegraph/handoff/latest.md`
- Recent task: `.ai/codegraph/last-task.json`
- Context inference: `.ai/codegraph/context-resolution.json`
- Seed candidates: `.ai/codegraph/seed-candidates.json`
- Next action: `.ai/codegraph/next-action.json`
- Contract-aware risk: inspect `affected_contracts` and `architecture_chains`
  in the JSON report and next action payload
- Structured logs: `.ai/codegraph/logs/`
- Reports: `.ai/codegraph/reports/`
- Recovery steps: `TROUBLESHOOTING.md`

## Sharing with other people or agents

- Share the normal exported package with `export-skill` (consumer mode)
- Share `--mode debug-bundle` only when someone needs logs, reports, handoff, or last-error details for troubleshooting
