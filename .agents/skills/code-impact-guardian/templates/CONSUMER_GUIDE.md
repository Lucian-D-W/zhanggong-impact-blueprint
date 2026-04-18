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
- Check `.ai/codegraph/reports/impact-<task-id>.json` when another agent needs machine-readable context.
- Read `.ai/codegraph/build-decision.json` when you need to understand why the run trusted incremental vs full rebuild.

## Where to look on failure

- Status: run `python .agents/skills/code-impact-guardian/cig.py status`
- Handoff: `.ai/codegraph/handoff/latest.md`
- Recent task: `.ai/codegraph/last-task.json`
- Context inference: `.ai/codegraph/context-resolution.json`
- Seed candidates: `.ai/codegraph/seed-candidates.json`
- Next action: `.ai/codegraph/next-action.json`
- Structured logs: `.ai/codegraph/logs/`
- Reports: `.ai/codegraph/reports/`
- Recovery steps: `TROUBLESHOOTING.md`
