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

## Review Bundle Packaging

- Default external review bundle name: `Stage 13.zip` at the repository root.
- The zip should unpack into a single top-level folder named `Stage 13/`.
- A review bundle must be self-consistent: if it includes `tests/`, it must also include every fixture directory those tests depend on.
- For this repository that means review bundles should include:
  - `.agents/skills/code-impact-guardian/`
  - `.code-impact-guardian/`
  - `scripts/`
  - `tests/`
  - `examples/`
  - `benchmark/`
  - `README.md`
  - `AGENTS.md`
  - `STAGE13_REVIEW_GUIDE.md`
  - `STAGE13_CHANGELOG.md`
  - `review 0419.txt`
- Do not omit `benchmark/` when shipping `tests/test_stage9_workflow.py` or any benchmark-driven review/tests.
- Preserve repo-relative paths exactly; do not rewrite config paths inside the bundle just to make the zip smaller.
- Exclude reviewer-irrelevant noise by default:
  - `.git/`
  - `.ai/`
  - `dist/`
  - `build/`
  - `__pycache__/`
  - `*.pyc`
  - `*.pyo`
  - temporary logs
  - previous zip artifacts
- Fixture contents under `benchmark/` or `examples/` are not noise, even if they contain folders such as `dist/`, `build/`, or `.cache/`; keep them intact.
- After creating the zip, verify that the expected top-level entries are present, especially `benchmark/`, `tests/`, and `.agents/skills/code-impact-guardian/`.
