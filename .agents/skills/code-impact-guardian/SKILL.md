---
name: code-impact-guardian
description: Use this repo-local workflow before changing code. Build or refresh the graph, generate an impact report, edit only after the report exists, then update graph, report, evidence, and tests after the edit.
---

# Code Impact Guardian

This skill is a copyable repository workflow template.

It is not a platform product.
It is not a plugin.
It is not tied to any existing business codebase.

## Fixed workflow

1. `build`
2. `report`
3. read the report
4. edit code
5. `after-edit`

The workflow stays fixed even when adapters, profiles, or fixtures change.

## Stage 5 scope

Stage5 keeps the template lightweight and pushes these things forward:

- TS/JS family stays the main app-facing adapter
- Python stays the stable regression baseline
- mixed repos now use `primary_adapter` + `supplemental_adapters`
- `sql_postgres` is now a real supplemental adapter
- local markdown rules remain the main truth source
- generic fallback stays available

Python remains the first demonstration chain, not a product binding.
React / Next / Electron / Obsidian / Tauri remain TS/JS profile differences
instead of separate graph systems.
PostgreSQL is not a second workflow; it is supplemental graph enrichment.

## Durable graph rules

- Nodes: `file`, `function`, `test`, `rule`
- Edges: `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- Persist only direct edges
- Never persist indirect or transitive edges
- Compute transitive impact only during report generation

## Preferred commands

Start with:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --project-root .
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
```

Mixed repo with PostgreSQL:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --with sql-postgres --project-root .
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
```

Then:

```bash
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id your-task --seed fn:src/file.js:yourFunction
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id your-task --seed fn:src/file.js:yourFunction --changed-file src/file.js
```

Fixture demos:

```bash
python .agents/skills/code-impact-guardian/cig.py demo --fixture python_minimal
python .agents/skills/code-impact-guardian/cig.py demo --fixture tsjs_node_cli --workspace path/to/temp/workspace
python .agents/skills/code-impact-guardian/cig.py demo --fixture tsx_react_vite --workspace path/to/temp/workspace
python .agents/skills/code-impact-guardian/cig.py demo --fixture generic_minimal --workspace path/to/temp/workspace
python .agents/skills/code-impact-guardian/cig.py demo --fixture sql_pg_minimal --workspace path/to/temp/workspace
python .agents/skills/code-impact-guardian/cig.py demo --fixture tsjs_pg_compound --workspace path/to/temp/workspace
```

## Profile notes

Real profiles in stage5:

- `node-cli`
- `react-vite`

Preset-only profiles:

- `next-basic`
- `electron-renderer`
- `obsidian-plugin`
- `tauri-frontend`

## Generic fallback rule

In generic mode:

- graph stays file-level only
- `seeds` must list file seeds
- `report` must accept file seeds
- test and git evidence still need to be recorded

Do not pretend generic mode has function-level precision.

## Supplemental adapter rule

Stage5 allows:

- `primary_adapter`
- `supplemental_adapters`

Use supplemental adapters when the repo has an app language plus SQL or another
supporting language that should land in the same graph.

Do not create a separate workflow for supplemental adapters.
Do not invent new node or edge types to represent them.
Do not turn low-confidence query text into graph truth.

For SQL query hints:

- high confidence + unique target -> direct `CALLS`
- otherwise -> attrs/report hint only

## Expected outputs

- `.ai/codegraph/codegraph.db`
- `.ai/codegraph/build.log`
- `.ai/codegraph/reports/impact-<task-id>.md`
- `.ai/codegraph/test-results.json`
- available function seeds or file seeds from `seeds`
- SQL seeds when SQL/PostgreSQL is enabled
- lightweight process tables: `task_runs`, `edit_rounds`, `file_diffs`, `symbol_diffs`

## Evidence policy

- Git evidence is the default.
- GitHub permalink, blame, and compare stay optional.
- If git history is unavailable, record the reason instead of pretending it exists.
- If coverage is unavailable, record the reason instead of fabricating coverage-backed results.
- Local markdown rules remain the main truth source for rule documents.
- Optional external docs may supplement the workflow, but never replace the graph.
