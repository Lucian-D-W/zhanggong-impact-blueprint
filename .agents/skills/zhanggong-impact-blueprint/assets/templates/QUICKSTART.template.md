# ZG Impact Blueprint Quickstart

## Install GitNexus first

```bash
npm install -g gitnexus
gitnexus --version
```

Use `zhanggong` as the daily entrypoint after GitNexus is installed. Stage 20
uses GitNexus as the default graph provider and keeps workflow ownership in
zhanggong.

## Shortest path

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root . --dry-run
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py build --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

If the repo has not been initialized yet, `analyze` will still auto-run the
minimal setup it needs. For real repos, `setup --minimal` is the preferred
explicit first step because it keeps the first write small and predictable.

These high-level commands automatically create:

- `.zhanggong-impact-blueprint/config.json`
- `.zhanggong-impact-blueprint/schema.sql`
- `.ai/codegraph/`
- a managed `.gitignore` block

Use `setup --full` only when you explicitly want:

- `AGENTS.md` managed block
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`
- `CONSUMER_GUIDE.md`

Calibration and verification priorities for real repos:

- user-facing entrypoint is still `cig.py`, not direct GitNexus workflow commands
- repo-local config wins over profile fallback
- package scripts beat profile fallback
- `calibrate` is the step that checks what adapter and test command the repo will really use
- default `graph_provider` is `gitnexus`
- GitNexus enriches graph/context/impact, but `finish`, baseline/no_regression, and handoff still belong to zhanggong
- Stage 20 uses direct `gitnexus` CLI first; do not assume `npx gitnexus analyze` is reliable on Windows
- if GitNexus is missing, unindexed, or path-incompatible, the workflow falls back to the internal provider instead of blocking the repo
- if GitNexus emits `.claude/`, `CLAUDE.md`, or `.gitignore` noise during indexing, zhanggong suppresses that root-level noise so the repo still feels like a zhanggong workflow
- `baseline` is the step that distinguishes historical red from a new regression

## Profile examples

Python:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --profile python-basic --project-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze
python .agents/skills/zhanggong-impact-blueprint/cig.py finish
```

TS/JS:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --profile node-cli --project-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file src/cli.js
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

Mixed TS/JS + Python:

```json
{
  "primary_adapter": "tsjs",
  "supplemental_adapters": ["python"]
}
```

Historically red full suite:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py baseline --workspace-root . --capture-current
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

## Output modes

- `analyze` defaults to brief terminal output
- use `--json` or `--full-json` when a script needs the full payload
- each report writes both `.md` and `.json`
- `brief` is the daily-use mode and intentionally short
- read `affected_contracts` and `architecture_chains` when API, route, event,
  table, config/env, or IPC changes may be involved
- `analyze --json` now reports `graph_provider`, `provider_status`, and provider evidence summary
- treat low-confidence `DEPENDS_ON` as fallback evidence, not parser certainty
- use `--patch-file <path>` when your editor or agent already has a diff file
- use `--changed-line <path:line>` only when auto context inference still needs help
- if `analyze` cannot infer enough context, it will tell you to pass `--changed-file`, `--patch-file`, initialize git, or use `--allow-fallback`

## When you normally do not trigger the workflow

- comment-only edits outside `docs/rules`
- formatting-only edits that do not change tokens or behavior
- generated/cache/build output files
- README/docs copy edits that do not modify rules, setup commands, or test commands

Low-level commands remain available for advanced use:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py init
python .agents/skills/zhanggong-impact-blueprint/cig.py doctor
python .agents/skills/zhanggong-impact-blueprint/cig.py detect
python .agents/skills/zhanggong-impact-blueprint/cig.py build
python .agents/skills/zhanggong-impact-blueprint/cig.py seeds
python .agents/skills/zhanggong-impact-blueprint/cig.py report --seed <seed>
python .agents/skills/zhanggong-impact-blueprint/cig.py after-edit --seed <seed> --changed-file <relative-path>
```

`setup`, `health`, `analyze`, and `finish` remain the preferred daily-use path.

## Runtime artifacts

- Graph DB: `.ai/codegraph/codegraph.db`
- Logs: `.ai/codegraph/logs/`
- Recent task: `.ai/codegraph/last-task.json`
- Reports: `.ai/codegraph/reports/`
- Handoff: `.ai/codegraph/handoff/latest.md`
- Build trust: `.ai/codegraph/build-decision.json`
- Context inference: `.ai/codegraph/context-resolution.json`
- Seed candidates: `.ai/codegraph/seed-candidates.json`
- Next action: `.ai/codegraph/next-action.json`
- Baseline status: `.ai/codegraph/baseline-status.json`
- Final status: `.ai/codegraph/status.json`
- Contract chains: read `affected_contracts` and `architecture_chains` inside
  the report JSON and `next-action.json`
- Health: `python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .`

