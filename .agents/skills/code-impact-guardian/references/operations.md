# Operations

## Daily path

1. `setup`
2. `analyze`
3. read `.ai/codegraph/next-action.json`
4. if present, read `affected_contracts` and `architecture_chains`
5. edit code
6. `finish`
7. `status`

## When setup is auto-run

If `.code-impact-guardian/config.json` is missing, agents should run:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
```

before asking the user anything.

## What analyze means

`analyze` is the mandatory pre-edit checkpoint. It resolves context, selects or
recommends a seed, builds or refreshes the graph, and writes the brief report
plus machine-readable artifacts such as `next-action.json`.

For Stage 16-style work, those artifacts can include contract-oriented surfaces
such as:

- `affected_contracts`
- `architecture_chains`

Use them when API, route, event, table, config/env key, or IPC changes might
reach beyond function `CALLS`.

## What finish means

`finish` is the mandatory post-edit checkpoint. It refreshes
graph/report/evidence, runs the budget-appropriate test scope, updates
handoff, and records warnings honestly.
