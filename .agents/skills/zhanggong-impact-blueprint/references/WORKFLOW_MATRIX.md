# Workflow Matrix

| Lane | Use For | Examples | Commands | Test Expectation |
| --- | --- | --- | --- | --- |
| bypass | Non-runtime, non-rule, non-agent-behavior edits | archive notes, ordinary docs copy edits, diagrams, screenshots, review prose | optional `classify-change`; no required `analyze`/`finish` | none |
| lightweight | Agent/workflow/process text that does not directly change code behavior | `AGENTS.md`, `SKILL.md`, quickstart/troubleshooting text, handoff templates, setup instructions | `classify-change`; optional `analyze` for structure | usually none |
| full guardian | Runtime or behavior-affecting changes | source, tests, config, schema, SQL, env, dependencies, rules, commands, CLI behavior | `health` if unclear, `analyze`, edit, `finish` | budget-driven targeted/configured/full |

## Boundary Rules

- Plain README copy edits should not be pulled into full guardian unless they change rules, setup, test, or command behavior.
- Documentation that changes how agents behave is lightweight.
- `docs/rules/**` is full guardian because it changes behavioral constraints.
- Any source, test, config, schema, SQL, env, dependency, or command change is full guardian.
- Mixed changes take the highest lane needed by any file.

## Lane Signals

`classify-change` and `next-action.json` both expose:

- `workflow_lane`
- `lane`
- `lane_explanation`
- `change_class`
- `verification_budget`
- `recommended_test_scope`

Use `workflow_lane` for the product-level answer and `change_class` for the underlying classifier bucket.
