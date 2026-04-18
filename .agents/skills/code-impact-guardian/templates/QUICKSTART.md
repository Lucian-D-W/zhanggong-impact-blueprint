# Code Impact Guardian Quickstart

## Shortest path

```bash
python .agents/skills/code-impact-guardian/cig.py init --project-root . --write-agents-md --write-gitignore
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id my-task --seed <seed>
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id my-task --seed <seed> --changed-file <relative-path>
```

## Profile examples

Python:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile python-basic --project-root . --write-agents-md --write-gitignore
```

TS/JS:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --project-root . --write-agents-md --write-gitignore
```

TS/JS + PostgreSQL:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --with sql-postgres --project-root . --write-agents-md --write-gitignore
```

## Runtime artifacts

- Graph DB: `.ai/codegraph/codegraph.db`
- Logs: `.ai/codegraph/logs/`
- Reports: `.ai/codegraph/reports/`
- Handoff: `.ai/codegraph/handoff/latest.md`
