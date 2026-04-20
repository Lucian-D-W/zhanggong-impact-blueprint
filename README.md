# 张工的施工图 / ZhangGong Impact Blueprint

张工的施工图 / ZhangGong Impact Blueprint is a repo-local impact atlas plus verification guardrail for agent-driven edits.

It answers a practical question before and after a change:

`If this file changes, what else should I read, verify, and keep honest before I claim it is safe enough to hand off?`

## What it is

- a copyable skill folder, not a hosted platform
- a repo-local SQLite graph with direct edges only
- a lightweight atlas for functions, tests, rules, and non-function contract surfaces
- a verification guardrail that helps choose bypass, lightweight, targeted, configured, or full validation
- a repair loop that widens the reading surface when repeated failures suggest the agent is patching too locally

## What it is not

- not an LSP
- not a runtime trace or profiler
- not embedding or semantic search
- not CI history learning
- not an automatic planner that decides for the agent
- not a proof system that turns `tests_passed` into “safe”

The system only does three things:

- make graph facts visible
- mark uncertainty clearly
- keep runtime artifacts and release packaging clean

## Quick workflow

1. Run `python .agents/skills/zhanggong-impact-blueprint/cig.py health` when repo state is unclear.
2. Run `python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>`.
3. Read `change_class`, `verification_budget`, `affected_contracts`, and `atlas_views`.
4. Edit only after reading the relevant view.
5. Run `python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted` or the heavier budget-recommended scope.
6. Read the refreshed `next-action.json` and handoff output.
7. If the same failure repeats, stop local patching and read `loop_atlas_views` before changing code again.

## When to skip the full flow

Use bypass or lightweight flow for:

- ordinary Markdown notes and summaries
- archives and historical notes
- diagrams and images
- formatting-only edits
- lightweight copy updates that do not change rules, commands, tests, config, schema, or runtime behavior

Do not drag every Markdown change into a full guardian run. The full flow is for source, tests, rules, config, schema, dependency, API, route, event, IPC, SQL, env, and config-surface changes.

## Atlas views

`affected_contracts` keeps the full fact list.

`atlas_views` is the reading layer. It reorganizes existing graph facts so an agent can read the right booklet without pretending the system already made the decision.

- `bilateral_contract`: puts both sides together, such as sender and handler, emit and handle, register and invoke, backend endpoint and frontend caller
- `page_flow`: shows route to component to child component to prop or flow
- `data_flow`: shows function or endpoint to query or mutation to SQL table to migration or tests
- `config_surface`: shows env var or config key to reader path to affected flow
- `uncertainty`: isolates low-confidence matches such as `DEPENDS_ON`, dynamic names, low-confidence extractors, and file-level fallback

## Reading examples

- IPC change: read the `bilateral_contract` view so the renderer send side and the main handle side are reviewed together.
- Route or component change: read the `page_flow` view so the page chain is reviewed together.
- SQL migration or query change: read the `data_flow` view so query, mutation, table, and migration context are read together.
- Env or config change: read the `config_surface` view so every reader path is visible before editing.
- `DEPENDS_ON` or low-confidence edges: read the `uncertainty` view as a hint list, not as proof.

## Verification budget

- `B0`: bypass-class non-runtime edits
- `B1`: lightweight documentation or process edits
- `B2`: targeted tests
- `B3`: configured tests
- `B4`: full tests plus dependency or schema review

Passing tests means only that the chosen tests passed. It does not mean the change is fully safe.

## Repeated failure behavior

Repeated failure is treated as a sign that the reading surface is too narrow.

- at repeated failures, widen the atlas surface first
- at three retries, uncertainty must be read explicitly
- at four retries, stop local patching and move to full-chain review plus full validation

The repair loop should not degrade into “just run more tests.” Its real job is to widen what the agent reads.

## Release check

Before publishing the public skill folder, run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py release-check --workspace-root . --skill-only
```

It checks for:

- private names or private doc examples
- absolute user paths
- temp-path leaks
- token-like secrets
- stale stage text in the public skill
- private config files
- `.ai/codegraph` runtime artifacts inside the exported skill folder

## Export modes

Consumer export:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py export-skill --out path/to/exported-skill
```

Single-folder export:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py export-skill --mode single-folder --out path/to/exported-skill
```

Debug bundle export:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py export-skill --mode debug-bundle --out path/to/exported-debug-bundle
```

## Primary docs

- `.agents/skills/zhanggong-impact-blueprint/SKILL.md`
- `AGENTS.md`
- `docs/archive/STAGE17_CHANGELOG.md`
- `docs/archive/STAGE17_REVIEW_GUIDE.md`

