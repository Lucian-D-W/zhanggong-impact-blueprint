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
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/app.py
```

3. Edit the code.

4. Refresh graph, report, evidence, and tests:

```bash
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/app.py
```

## Python

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile python-basic --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/app.py
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/app.py
```

## TS/JS

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/cli.js
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/cli.js
```

## TS/JS + PostgreSQL

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --with sql-postgres --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/sessionQueries.js
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/sessionQueries.js
```

## Where to look on failure

- Status: `.ai/codegraph/handoff/latest.md`
- Recent task: `.ai/codegraph/last-task.json`
- Structured logs: `.ai/codegraph/logs/`
- Reports: `.ai/codegraph/reports/`
- Recovery steps: `TROUBLESHOOTING.md`
