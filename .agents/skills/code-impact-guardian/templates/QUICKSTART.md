# Code Impact Guardian Quickstart

## Shortest path

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file <relative-path> --changed-line <relative-path:line>
python .agents/skills/code-impact-guardian/cig.py finish --changed-file <relative-path>
```

These high-level commands automatically create:

- `AGENTS.md`
- `.gitignore`
- `.code-impact-guardian/config.json`
- `.code-impact-guardian/schema.sql`
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`
- `CONSUMER_GUIDE.md`

## Profile examples

Python:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile python-basic --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/app.py --changed-line src/app.py:10
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/app.py
```

TS/JS:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/cli.js --changed-line src/cli.js:5
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/cli.js
```

TS/JS + PostgreSQL:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --with sql-postgres --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze --changed-file src/sessionQueries.js --changed-line src/sessionQueries.js:6
python .agents/skills/code-impact-guardian/cig.py finish --changed-file src/sessionQueries.js
```

## Output modes

- `analyze` and `status` default to `brief`
- use `--full` when you need more detail
- each report writes both `.md` and `.json`

Low-level commands remain available for advanced use:

```bash
python .agents/skills/code-impact-guardian/cig.py init
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --seed <seed>
python .agents/skills/code-impact-guardian/cig.py after-edit --seed <seed> --changed-file <relative-path>
```

## Runtime artifacts

- Graph DB: `.ai/codegraph/codegraph.db`
- Logs: `.ai/codegraph/logs/`
- Recent task: `.ai/codegraph/last-task.json`
- Reports: `.ai/codegraph/reports/`
- Handoff: `.ai/codegraph/handoff/latest.md`
