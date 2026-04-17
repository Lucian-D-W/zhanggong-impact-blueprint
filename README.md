# Code Impact Guardian

Code Impact Guardian is a lightweight, repo-local skill workflow for safer code
edits.

It is intentionally shaped as:

- `AGENTS.md`
- one repo-scoped skill
- one SQLite fact store
- one fixed impact report flow
- a small set of copyable scripts

It is not a plugin.
It is not a platform product.
It is meant to be copied into another repository and adapted through config,
profiles, and thin parser backends.

## Fixed workflow

The workflow stays fixed across every stage:

1. build / refresh graph
2. generate impact report
3. allow code edits
4. update graph / report / evidence after edit
5. run relevant tests and record outcome

## Current support level

### Stage 1

- real Python minimal fixture
- real `coverage.py` import
- SQLite graph + report + after-edit loop

### Stage 2

- generic file-level fallback
- minimal `.js/.ts` adapter
- unified CLI entry: `cig.py`

### Stage 3

- lightweight process recording
- `task_runs`, `edit_rounds`, `file_diffs`, `symbol_diffs`
- `init` and `doctor`
- optional doc source hook while keeping local markdown as default truth

### Stage 4

- TS/JS family promoted to a first-class adapter
- profile-aware init / detect / doctor
- `.js`, `.ts`, `.jsx`, `.tsx` scanning
- raw V8 coverage path for TS/JS profiles
- better seed discovery and report metadata
- lightweight placeholder slots for Rust-lite and SQL/PostgreSQL

## Adapter status

### Python

Python remains the most stable baseline.

Current Python behavior:

- supports `file`, `function`, `test`, `rule`
- supports `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- imports real `coverage.py` data
- keeps stage1 / stage2 / stage3 regressions as the main stability gate

Python is still the first demonstration chain, not a product binding.

### TS/JS family

TS/JS is now the main expansion target in stage4.

Current TS/JS behavior:

- supports `.js`, `.ts`, `.jsx`, `.tsx`
- recognizes:
  - function declarations
  - exported const arrow functions
  - React function components
  - custom hooks (`useX`)
  - minimal class methods
- parses:
  - `import`
  - `export`
  - re-export
  - `require`
  - `module.exports`
- records richer parser metadata in node attrs
- improves seed discovery and report display for definition/reference hints
- supports node:test and basic `test` / `it` / `describe` / `test.describe`
- has a real raw V8 coverage path for profile-driven TS/JS projects

Stage4 still keeps TS/JS as one family adapter.
React, Next, Electron, Obsidian, and Tauri are profile differences, not
separate graph systems.

### Generic fallback

When a language is not supported yet, the workflow still runs through the
generic adapter.

Generic mode:

- stays file-level only
- still supports `build`, `seeds`, `report`, `after-edit`
- still records test outcome and git evidence
- never pretends to have function-level precision

Use generic fallback when:

- the project language is not supported yet
- you only need config / file / rule impact coverage for now
- you want the workflow today without waiting for a parser backend

## Profiles

Stage4 adds a lightweight profile layer for project defaults.

Real profiles in stage4:

- `node-cli`
- `react-vite`

Preset-only profiles in stage4:

- `next-basic`
- `electron-renderer`
- `obsidian-plugin`
- `tauri-frontend`

Profiles affect:

- globs
- test command selection
- coverage command selection
- doctor checks
- default rule/doc expectations

Profiles do not:

- change the schema
- fork the core workflow
- create a second adapter system

## Unified CLI

The unified entry point stays thin:

```bash
python .agents/skills/code-impact-guardian/cig.py <command>
```

Commands:

- `init`
- `doctor`
- `detect`
- `build`
- `seeds`
- `report`
- `after-edit`
- `demo`

### Shortest path in a real project

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --project-root .
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id your-task --seed fn:src/your_file.js:yourFunction
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id your-task --seed fn:src/your_file.js:yourFunction --changed-file src/your_file.js
```

## Profile-aware init

Examples:

Python:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile python-basic --project-root .
```

Node CLI:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --project-root .
```

React + Vite:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile react-vite --project-root .
```

If you do not supply a profile, `project_profile` stays `auto` and `detect`
will fall back to a lightweight heuristic:

- Python files -> `python-basic`
- TS/JS family files -> a TS/JS profile guess
- otherwise -> `generic-file`

## Seeds and reports

`seeds` now returns both ids and lightweight metadata.

For TS/JS family projects, seed details can include:

- `definition_kind`
- `exported`
- `is_component`
- `is_hook`
- `class_name`
- `reference_hints`

`report` now shows:

- detected adapter and profile
- seed definition metadata
- reference hints from parser attrs
- direct callers / callees / tests / rules
- transitive paths computed only at report time

## Rules and doc sources

Local markdown rules remain the default path and the default truth source.

Rule docs are still expected in local markdown with stable ids, for example:

```text
docs/rules/*.md
```

Optional doc sources can be added later through `doc_source_adapter`, but they
only supplement local docs. They never replace the local code graph as the main
truth source.

If external docs are supplied through config, stage4 can snapshot them into the
local doc cache under `.ai/codegraph/doc-cache/` for later review.

## Example fixtures

Current fixtures:

- `examples/python_minimal/`
- `examples/tsjs_minimal/`
- `examples/generic_minimal/`
- `examples/tsjs_node_cli/`
- `examples/tsx_react_vite/`
- `examples/rust_lite_placeholder/`
- `examples/sql_pg_placeholder/`

Real stage4 TS/JS fixtures:

- `tsjs_node_cli` for `node-cli`
- `tsx_react_vite` for `react-vite`

## Copying the skill into a real project

Copy these paths into the target repo:

- `AGENTS.md`
- `.agents/skills/code-impact-guardian/`
- `.code-impact-guardian/config.json`
- `.code-impact-guardian/schema.sql`

Then:

1. run `init` with a profile
2. run `doctor`
3. run `detect`
4. run `build`
5. run `seeds`
6. run `report`
7. make the edit
8. run `after-edit`

### Real Python project

1. Copy the skill files into the repo.
2. Add or confirm local rule markdown files such as `docs/rules/*.md`.
3. Initialize:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile python-basic --project-root .
```

4. Doctor:

```bash
python .agents/skills/code-impact-guardian/cig.py doctor
```

5. Build and inspect seeds:

```bash
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
```

6. Generate a report for the function you plan to touch:

```bash
python .agents/skills/code-impact-guardian/cig.py report --task-id auth-fix --seed fn:src/app.py:login
```

7. Edit the code, then refresh graph, report, evidence, and tests:

```bash
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id auth-fix --seed fn:src/app.py:login --changed-file src/app.py
```

### Real TS/JS project

Node CLI style:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile node-cli --project-root .
```

React + Vite style:

```bash
python .agents/skills/code-impact-guardian/cig.py init --profile react-vite --project-root .
```

Then run the same fixed workflow:

```bash
python .agents/skills/code-impact-guardian/cig.py doctor
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id ui-fix --seed fn:src/AppShell.tsx:AppShell
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id ui-fix --seed fn:src/AppShell.tsx:AppShell --changed-file src/AppShell.tsx
```

## Verification

Stage1 regression:

```bash
python -m unittest tests.test_stage1_workflow -v
```

Stage2 regression:

```bash
python -m unittest tests.test_stage2_workflow -v
```

Stage3 regression:

```bash
python -m unittest tests.test_stage3_workflow -v
```

Stage4 workflows:

```bash
python -m unittest tests.test_stage4_workflow -v
```

## Roadmap placeholders

Stage4 only reserves these next steps:

- Rust-lite backend name and example placeholder
- SQL/PostgreSQL backend name and example placeholder

No parser or tests are shipped for those two yet.
