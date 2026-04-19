# Code Impact Guardian

Code Impact Guardian is a lightweight, repo-local skill template for safer
agent-driven code changes.

It is designed to answer one practical question before an edit lands:

`If I change this, what else do I risk breaking?`

The template stays intentionally small:

- one repo-local skill folder
- one SQLite graph
- one direct-edge workflow
- one unified CLI
- one export path for consumer repos

It is not a hosted platform. It is meant to be copied into another repository
and used by agents as part of the normal edit loop.

## Current focus

The repository has moved beyond the earlier Stage 10 daily-driver work. The
current shape includes the Stage 13 "Real-Use Intelligence Layer" and the
Stage 14 "Adaptive Verification Orchestrator" additions:

- verification budgets (`B0` through `B4`)
- `targeted`, `configured`, and `full` test scopes
- `recommend-tests` for executable affected-test commands
- `--shadow-full` calibration for targeted verification
- local test-history ranking
- runtime integration pack files under `.ai/codegraph/runtime/`
- multidimensional trust instead of a single trust flag
- early runtime-contract graph support for env/config/ipc/sql-style edges

The repo is still a development source for the template, so some review-bundle
documents remain at the root for compatibility even though the product workflow
has advanced.

## Fixed workflow

The core workflow remains stable:

1. run `health` when repo readiness is unclear
2. run `analyze`
3. read the brief report and `.ai/codegraph/next-action.json`
4. edit only after the impact context is clear
5. run `finish` with the budget-driven scope
6. use `--shadow-full` when targeted verification needs calibration

For agents, the canonical operational instructions live in:

- `.agents/skills/code-impact-guardian/SKILL.md`
- `AGENTS.md`
- `.ai/codegraph/*` runtime state files

## Current support level

### Python

- stable regression baseline
- `file`, `function`, `test`, `rule`
- direct `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- real `coverage.py` support with honest fallback when coverage is unavailable

### TS/JS family

- `.js`, `.ts`, `.jsx`, `.tsx`
- function declarations
- exported const arrow functions
- React function components
- custom hooks
- minimal class methods
- import / export / re-export / require / module.exports
- `node:test`, Jest, and Vitest style detection
- conservative file-level test recommendations when method-level mapping is not available

### SQL/PostgreSQL supplemental

- lightweight SQL supplemental adapter
- SQL files as `file` nodes
- PostgreSQL routines as `function` nodes
- high-confidence SQL `CALLS`
- high-confidence SQL test `COVERS`
- honest no-coverage behavior when runtime coverage is not available

### Runtime-contract graph

The graph still centers on `file`, `function`, `test`, and `rule`, but the
repo now also has lightweight support for identifying higher-level contracts
such as env vars, config keys, endpoints, routes, ipc channels, SQL table
references, and Playwright-style flow hints.

These contract nodes are intentionally lightweight and should not be treated as
fully exhaustive parser truth.

## Development repo vs consumer install

This repository is the development source.

It contains:

- examples
- tests
- benchmark fixtures
- review-bundle documents
- archived process/history documents

The consumer-facing install path is still:

1. copy only `.agents/skills/code-impact-guardian/` into the target repo
2. run `python .agents/skills/code-impact-guardian/cig.py setup --project-root .`

That single-folder install generates:

- `AGENTS.md`
- `.gitignore`
- `.code-impact-guardian/config.json`
- `.code-impact-guardian/schema.sql`
- `QUICKSTART.md`
- `TROUBLESHOOTING.md`
- `CONSUMER_GUIDE.md`

## Documentation map

The repo now separates current operating docs from archived process docs.

Current docs:

- `README.md`
- `AGENTS.md`
- `docs/README.md`
- `benchmark/README.md`
- `docs/demo/without-vs-with-skill.md`

Compatibility review docs:

- `STAGE13_REVIEW_GUIDE.md`
- `STAGE13_CHANGELOG.md`

Archived process/history docs:

- `docs/archive/README.md`

## Exporting the skill

### Consumer export

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --out path/to/exported-skill
```

This is the default. It produces the consumer-safe package and does not include
`.ai` runtime artifacts.

### Debug bundle export

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --mode debug-bundle --out path/to/exported-debug-bundle
```

Use this only for troubleshooting or handoff. It may include reports, logs,
handoff notes, and last-error snapshots.

### Single-folder export

```bash
python .agents/skills/code-impact-guardian/cig.py export-skill --mode single-folder --out path/to/exported-skill
```

This produces only:

```text
.agents/skills/code-impact-guardian/
```

## Recommended commands

### High-level commands

These are the main user-facing commands now:

```bash
python .agents/skills/code-impact-guardian/cig.py setup --project-root .
python .agents/skills/code-impact-guardian/cig.py health
python .agents/skills/code-impact-guardian/cig.py analyze
python .agents/skills/code-impact-guardian/cig.py recommend-tests --workspace-root . --task-id <task-id>
python .agents/skills/code-impact-guardian/cig.py install-integration-pack
python .agents/skills/code-impact-guardian/cig.py finish --test-scope targeted
python .agents/skills/code-impact-guardian/cig.py finish --test-scope targeted --shadow-full
```

What they do:

- `setup` = initialize config, schema, consumer docs, and repo defaults
- `health` = report readiness, trust freshness, and recovery hints
- `analyze` = infer context, refresh or reuse the graph, and write next-action guidance
- `recommend-tests` = turn direct test seeds into executable commands
- `install-integration-pack` = write runtime-neutral repo guidance and session contract files
- `finish` = refresh evidence, run the chosen verification scope, and update handoff/status state

Useful flags:

- `--changed-file <path>`
- `--changed-line <path:line>`
- `--patch-file <path>`
- `--allow-fallback`
- `--full`
- `--shadow-full`
- `--test-scope targeted|configured|full`

### Budget-driven verification

Verification is no longer a simple "light vs full" choice.

- `B0` = no-op or docs-only
- `B1` = health + analyze only
- `B2` = targeted tests
- `B3` = configured tests
- `B4` = full tests plus dependency/schema review

The verification budget is written to:

- `.ai/codegraph/verification-policy.json`
- `.ai/codegraph/next-action.json`
- finish/test results payloads

## Profiles

Real working profiles:

- `python-basic`
- `node-cli`
- `react-vite`

Setup-ready profiles:

- `next-basic`
- `electron-renderer`
- `obsidian-plugin`
- `tauri-frontend`

Profiles only change config defaults, doctor expectations, and suggested
commands. They do not create separate graph systems.

## Structured runtime artifacts

Runtime data is written under:

```text
.ai/codegraph/
```

Key files:

- graph DB: `.ai/codegraph/codegraph.db`
- reports: `.ai/codegraph/reports/`
- logs: `.ai/codegraph/logs/`
- handoff: `.ai/codegraph/handoff/latest.md`
- context resolution: `.ai/codegraph/context-resolution.json`
- next action: `.ai/codegraph/next-action.json`
- verification policy: `.ai/codegraph/verification-policy.json`
- test history: `.ai/codegraph/test-history.jsonl`
- calibration history: `.ai/codegraph/calibration.jsonl`
- pending changes: `.ai/codegraph/pending-changes.jsonl`

When the integration pack is installed, runtime-neutral session docs also live
under:

```text
.ai/codegraph/runtime/
```

## Trust and safety

`tests passed` is useful evidence, but it is not proof that a change is safe.

The runtime now separates:

- seed confidence
- graph trust
- parser trust
- dependency status
- test signal
- coverage signal
- context completeness
- overall trust

That split is intentional. The skill should help an agent avoid overclaiming,
not manufacture confidence.

## Recovery and handoff

Read in this order when something goes wrong:

1. `.ai/codegraph/logs/last-error.json`
2. `.ai/codegraph/handoff/latest.md`
3. `TROUBLESHOOTING.md`

Use:

```bash
python .agents/skills/code-impact-guardian/cig.py status
```

to inspect the latest build/report/finish state, trust decision, inferred
context, and recommended next step.

## Verification

Focused validation:

```bash
python -m unittest tests.test_stage11_workflow tests.test_stage13_workflow -v
python -m unittest tests.test_stage14_workflow -v
```

Broader regression:

```bash
python -m unittest tests.test_stage9_workflow tests.test_stage10_workflow tests.test_stage11_workflow tests.test_stage13_workflow tests.test_stage14_workflow -v
```

Full current workflow matrix:

```bash
python -m unittest discover -s tests -p test_*.py -v
```
