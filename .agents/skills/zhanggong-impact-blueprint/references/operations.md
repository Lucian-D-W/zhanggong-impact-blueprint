# Operations

## Daily path

Use the smallest honest lane.

1. Run `setup --dry-run --preview-changes` before first adoption.
2. Run minimal `setup` only when the repo is ready to accept runtime files.
3. Use `classify-change` when lane choice is unclear.
4. For full guardian work, run `health` or `calibrate` if repo readiness is unclear.
5. For full guardian work, run `analyze` before editing.
6. Read the brief first, then `.ai/codegraph/next-action.json` if more detail is needed.
7. If present, read `affected_contracts` and `atlas_views`.
8. Edit.
9. For full guardian work, run `finish`.
10. Read `final-state.json` and `handoff/latest.md`.

## When setup is needed

If `.zhanggong-impact-blueprint/config.json` is missing, agents should preview first:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root . --dry-run --preview-changes
```

Then run minimal setup only when continuing with zhanggong in that repo:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --workspace-root . --project-root .
```

## What analyze means

For full guardian work, `analyze` is the pre-edit checkpoint. It resolves
context, selects or recommends a seed, builds or refreshes the graph, and
writes the brief report plus machine-readable artifacts such as
`next-action.json`.

For contract/risk work, those artifacts can include:

- `affected_contracts`
- `atlas_views`

Use them when API, route, event, table, config/env key, or IPC changes might
reach beyond local function calls.

## What finish means

For full guardian work, `finish` is the post-edit checkpoint. It refreshes
graph/report/evidence, runs the budget-appropriate current-task test scope,
updates handoff, and records warnings honestly.

