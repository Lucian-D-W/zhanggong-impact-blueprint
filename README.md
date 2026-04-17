# Code Impact Guardian

Code Impact Guardian is a lightweight, repo-local workflow template for safer
code edits.

It is intentionally shaped as:

- `AGENTS.md`
- one repo-scoped skill
- one SQLite fact store
- one fixed impact report flow
- a small set of copyable scripts

It is **not** a platform product.
It is **not** a plugin.
It is designed to be copied into another repository and extended through config
plus thin adapters.

## Fixed workflow

The workflow stays the same across Stage 1 and Stage 2:

1. build / refresh graph
2. generate impact report
3. allow code edits
4. update graph / report / evidence after edit
5. run relevant tests and record outcome

## Current support

### Stage 1

Stage 1 proved the workflow with a real Python minimal fixture plus
`coverage.py`.

That Python chain is only the first demonstration path.
It does **not** mean the workflow core is bound to Python.

### Stage 2

Stage 2 adds the smallest possible extension layer without changing the schema
or the fixed workflow:

- `generic` fallback for unsupported languages
- a minimal `tsjs` adapter for `.js` and `.ts`
- one unified entry point: `cig.py`

Stage 2 still keeps the template light:

- no plugin
- no platformization
- no new node or edge types
- no persisted transitive edges

## Adapter status

### Python

Python is the most complete chain today.

Current Python behavior:

- supports `file`, `function`, `test`, `rule`
- supports `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- supports `coverage.py`
- has a real end-to-end fixture: `examples/python_minimal/`

### TS/JS

TS/JS is now supported at the minimum Stage 2 level.

Current TS/JS behavior:

- supports `.js` and `.ts`
- supports `file`, `function`, `test`
- supports `DEFINES`, `CALLS`, `IMPORTS`
- records test outcome and git evidence
- coverage stays unavailable by default in Stage 2
- has a real end-to-end fixture: `examples/tsjs_minimal/`

This Stage 2 TS/JS adapter is intentionally small.
It does **not** add React-specific, Node-specific, Electron-specific, or
Tauri-specific logic yet.

### Generic fallback

When a project language is not yet supported, the workflow can still run in
`generic` fallback mode.

Current generic behavior:

- still supports `build`
- still supports `seeds`
- still supports `report`
- still supports `after-edit`
- still records test outcome and git evidence
- only works at **file level**

The generic adapter does **not** pretend to support function-level analysis.
It emits file seeds such as `file:src/settings.conf`.

## Unified entry

Stage 2 adds one thin command shell:

```bash
python .agents/skills/code-impact-guardian/cig.py <command>
```

Supported commands:

- `detect`
- `build`
- `seeds`
- `report`
- `after-edit`
- `demo`

Examples:

```bash
python .agents/skills/code-impact-guardian/cig.py detect
python .agents/skills/code-impact-guardian/cig.py build
python .agents/skills/code-impact-guardian/cig.py seeds
python .agents/skills/code-impact-guardian/cig.py report --task-id demo-login-impact --seed fn:src/app.py:login
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id demo-login-impact --seed fn:src/app.py:login --changed-file src/app.py
```

`cig.py` is only a thin entry shell.
The existing scripts still do the real work underneath.

## Demo fixtures

The repository now includes three fixtures:

- `examples/python_minimal/`
- `examples/tsjs_minimal/`
- `examples/generic_minimal/`

### Cross-platform demo commands

Python demo:

```bash
python scripts/demo_phase1.py
```

Unified fixture demos:

```bash
python .agents/skills/code-impact-guardian/cig.py demo --fixture python_minimal
python .agents/skills/code-impact-guardian/cig.py demo --fixture tsjs_minimal --workspace path/to/temp/workspace
python .agents/skills/code-impact-guardian/cig.py demo --fixture generic_minimal --workspace path/to/temp/workspace
```

The `--workspace` form copies the template into a disposable workspace,
initializes a temporary git repository there, and leaves the generated
artifacts in that copied workspace.

## Generated artifacts

Successful runs write real outputs under `.ai/codegraph/`:

- `codegraph.db`
- `build.log`
- `reports/impact-<task-id>.md`
- `test-results.json`
- `test-output-<task-id>.log`
- `coverage-<task-id>.json` when coverage is available

## Configuration

Configuration stays dependency-free and lives in:

```text
.code-impact-guardian/config.json
```

Important keys:

- `project_root`
- `language_adapter`
- `rules.globs`
- `python.*`
- `tsjs.*`
- `generic.*`
- `impact.max_depth`

`language_adapter` accepts:

- `auto`
- `python`
- `tsjs`
- `generic`

`auto` is intentionally lightweight:

- detect Python if Python source/test files are present
- otherwise detect TS/JS if `.js` or `.ts` source/test files are present
- otherwise fall back to `generic`

## Copying this into a real project

To reuse this template in another repository:

1. Copy these paths into the target repository:
   - `AGENTS.md`
   - `.agents/skills/code-impact-guardian/`
   - `.code-impact-guardian/config.json`
   - `.code-impact-guardian/schema.sql`
2. Update `.code-impact-guardian/config.json`:
   - point `project_root` at the real project
   - choose `language_adapter`
   - set source/test globs for the selected adapter
   - set the test command for that project
   - set `rules.globs` if your rule docs live elsewhere
3. Add Markdown rule files with stable `id` values in frontmatter.
4. Build the graph:

```bash
python .agents/skills/code-impact-guardian/cig.py build
```

5. List seed candidates:

```bash
python .agents/skills/code-impact-guardian/cig.py seeds
```

6. Generate the report for the function or file you plan to change:

```bash
python .agents/skills/code-impact-guardian/cig.py report --task-id your-task --seed fn:path/to/file.py:function_name
```

For generic fallback, use a file seed:

```bash
python .agents/skills/code-impact-guardian/cig.py report --task-id your-task --seed file:path/to/file.conf
```

7. Read the report, make the edit, then refresh graph, report, evidence, and
test outcome:

```bash
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id your-task --seed fn:path/to/file.py:function_name --changed-file path/to/file.py
```

## Verification

Stage 1 regression:

```bash
python -m unittest tests.test_stage1_workflow -v
```

Stage 2 workflows:

```bash
python -m unittest tests.test_stage2_workflow -v
```
