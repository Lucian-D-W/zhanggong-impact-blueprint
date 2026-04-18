# Operations

## Daily path

1. `setup`
2. `analyze`
3. edit code
4. `finish`
5. `status`

## When setup is auto-run

If `.code-impact-guardian/config.json` is missing, agents should run:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
```

before asking the user anything.

## What analyze means

`analyze` is the mandatory pre-edit checkpoint. It resolves context, selects or recommends a seed, builds or refreshes the graph, and writes the brief report plus machine-readable artifacts.

## What finish means

`finish` is the mandatory post-edit checkpoint. It refreshes graph/report/evidence, runs tests, updates handoff, and records warnings honestly.

