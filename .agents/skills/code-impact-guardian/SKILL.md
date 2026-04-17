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

The fixed workflow stays the same even when adapters change.

## Stage 2 scope

Stage 2 keeps the template lightweight and only adds:

- a thin unified entry: `cig.py`
- a minimal `.js/.ts` adapter
- a generic file-level fallback

Python remains the first demonstration chain, not a product binding.
Future React / Node.js work should extend the TS/JS family through config and
adapters instead of replacing the workflow or schema.

## Durable graph rules

- Nodes: `file`, `function`, `test`, `rule`
- Edges: `DEFINES`, `CALLS`, `IMPORTS`, `COVERS`, `GOVERNS`
- Persist only direct edges
- Never persist indirect or transitive edges
- Compute transitive impact only during report generation

## Preferred commands

Detect the active adapter:

```bash
python .agents/skills/code-impact-guardian/cig.py detect
```

Build or refresh:

```bash
python .agents/skills/code-impact-guardian/cig.py build
```

List seed candidates:

```bash
python .agents/skills/code-impact-guardian/cig.py seeds
```

Generate a report:

```bash
python .agents/skills/code-impact-guardian/cig.py report --task-id demo-login-impact --seed fn:src/app.py:login
```

Update after an edit:

```bash
python .agents/skills/code-impact-guardian/cig.py after-edit --task-id demo-login-impact --seed fn:src/app.py:login --changed-file src/app.py
```

Run a fixture demo:

```bash
python .agents/skills/code-impact-guardian/cig.py demo --fixture python_minimal
```

## Generic fallback rule

If the active project language is not supported yet, the workflow must still
continue through the generic adapter.

In generic mode:

- graph stays file-level only
- `seeds` must list file seeds
- `report` must accept file seeds
- test and git evidence still need to be recorded

Do not pretend generic mode has function-level precision.

## Expected outputs

- `.ai/codegraph/codegraph.db`
- `.ai/codegraph/build.log`
- `.ai/codegraph/reports/impact-<task-id>.md`
- `.ai/codegraph/test-results.json`
- available function seeds or file seeds from `seeds`

## Evidence policy

- Git evidence is the default.
- GitHub permalink, blame, and compare stay optional.
- If git history is unavailable, record the reason instead of pretending it exists.
- If coverage is unavailable, record the reason instead of fabricating coverage-backed results.
