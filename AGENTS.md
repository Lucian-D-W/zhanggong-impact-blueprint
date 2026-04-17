# Code Impact Guardian Working Agreement

This repository is a copyable workflow template, not a business project.

Whenever a task changes code, behavior, configuration, schema, or tests:

1. Run `build_graph.py`
2. Run `generate_report.py`
3. Read the impact report
4. Only then allow code edits
5. After edits, run `after_edit_update.py`

## Stage 1 defaults

- The first working demo uses the `examples/python_minimal/` fixture.
- That Python fixture is only the first proof that the workflow closes the loop.
- It does **not** mean the workflow core is bound to Python.
- Future TypeScript/JavaScript/React/Node.js support extends config and adapters without changing the main workflow.
- Repo-local config now lives at `.code-impact-guardian/config.json`.

## Guardrails

- Persist only direct edges.
- Never persist indirect or transitive impact as durable graph truth.
- Compute transitive impact only while generating the report.
- GitHub permalink, blame, and compare are optional evidence enhancements, not required dependencies.
- If coverage is unavailable, record that fact. Never fabricate coverage-backed results.
