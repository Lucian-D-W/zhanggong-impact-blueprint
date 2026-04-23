---
name: zhanggong-impact-blueprint
description: GitNexus-first repo-local impact workflow for code changes. Use when Codex will edit source files, tests, config/schema, commands, or behavior and should verify GitNexus, run analyze before editing, and run finish after editing while keeping zhanggong as the workflow owner.
---

# ZG Impact Blueprint

Use this skill to run the Stage 20 workflow for repo-local changes.

## Core model

- Use `zhanggong` as the user-facing workflow.
- Use `GitNexus` as the default graph provider.
- Keep `calibrate`, seed selection, verification budget, test command choice, `finish`, and handoff in zhanggong.
- Use the internal provider whenever GitNexus is not ready for the current repo.

## Install once per machine

1. Install GitNexus CLI:

```bash
npm install -g gitnexus
```

2. Verify the command:

```bash
gitnexus --version
```

3. Copy this skill into the target repo:

```text
./.agents/skills/zhanggong-impact-blueprint/
```

4. Initialize the repo-local files:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root .
```

## Use this workflow for

- source files
- tests
- config, schema, dependency, env, or SQL changes
- command and rule changes
- documentation that changes setup, test, or workflow behavior

## Daily flow

1. Run `health` when repo readiness is unclear.
2. Run `calibrate` to confirm the adapter, graph provider, and test command.
3. Run `analyze --workspace-root . --changed-file <path>` before editing.
4. Read `.ai/codegraph/next-action.json`.
5. Read `affected_contracts` and `atlas_views` when the change may cross API, route, event, IPC, SQL, config, or env surfaces.
6. Edit.
7. Run `finish` with the recommended scope.

## Preferred commands

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py setup --minimal --project-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py calibrate --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py health --workspace-root .
python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>
python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted
```

## Read these outputs

- `.ai/codegraph/next-action.json` for seed, budget, test scope, and provider status
- `.ai/codegraph/reports/*.md` and `.json` for impact details
- `.ai/codegraph/handoff/latest.md` for final state and handoff context

## Provider behavior

- Start with direct `gitnexus` CLI.
- Let zhanggong report `graph_provider`, `provider_status`, `provider_reason`, and fallback details.
- Continue with the internal provider when GitNexus is missing, unindexed, or path-incompatible.

## Need more detail?

Read these reference files only when you need deeper detail:

- `references/operations.md`
- `references/troubleshooting.md`
- `references/trust-model.md`
- `references/supported-modes.md`
