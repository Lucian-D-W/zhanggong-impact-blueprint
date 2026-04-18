# Code Impact Guardian Quickstart

## Shortest path

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
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
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

TS/JS:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

TS/JS + PostgreSQL:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --profile node-cli --with sql-postgres --project-root .
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py finish
```

## Output modes

- `analyze` and `status` default to `brief`
- use `--full` when you need more detail
- each report writes both `.md` and `.json`
- use `--patch-file <path>` when your editor or agent already has a diff file
- use `--changed-line <path:line>` only when auto context inference still needs help

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
