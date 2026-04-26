# ZG Impact Blueprint Consumer Guide

This guide is for repos that copied only:

`./.agents/skills/zhanggong-impact-blueprint/`

## Start Small

Preview first:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root .
```

Use `--full` only when the repo wants generated onboarding docs and AGENTS integration.

## Pick The Lane

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py classify-change --workspace-root . --changed-file <path>
```

- `bypass`: ordinary docs, archive notes, review prose, diagrams.
- `lightweight`: agent/workflow/process docs and templates.
- `full_guardian`: source, tests, config, schema, SQL, env, dependencies, rules, commands.

## Full Guardian Path

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

`analyze` is brief by default. It writes full evidence to:

- `.ai/codegraph/summary.json`
- `.ai/codegraph/facts.json`
- `.ai/codegraph/inferences.json`
- `.ai/codegraph/next-action.json`
- `.ai/codegraph/reports/`

## Daily-Use Rules

- Provider is not workflow owner; zhanggong remains the workflow owner.
- Repo config beats recent facts, package scripts, fallbacks, and defaults.
- Explicit changed files beat dirty-worktree inference.
- Multi-entry changes should expose primary and secondary seeds instead of blocking by default.
- Tests passed does not mean safe.
- Baseline red does not automatically mean this edit broke the repo.

## Failure Recovery

- Start with `health` for readiness.
- Use `calibrate` when adapter or test command choice looks wrong.
- Use `facts.json` for observed state.
- Use `inferences.json` for uncertainty/trust/fallback.
- Use `handoff/latest.md` and `final-state.json` after finish.
