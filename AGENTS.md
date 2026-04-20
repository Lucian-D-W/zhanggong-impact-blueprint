# ZG Impact Blueprint Working Agreement

This repository is a copyable workflow template, not a business project.

## Final boundary

ZG Impact Blueprint is a repo-local impact atlas plus verification guardrail.

It is not:

- an LSP
- a runtime trace system
- an embedding search layer
- a CI history learner
- an automatic planner that decides for the agent

The system should only:

- show graph facts
- mark uncertainty
- keep logs, resources, and release packaging clean

## When to run the full flow

Whenever a task changes code, behavior, configuration, schema, tests, rules, dependencies, API surfaces, routes, events, IPC, SQL, env vars, or config keys:

1. Run `build_graph.py`.
2. Run `generate_report.py`.
3. Read the impact report.
4. Only then allow code edits.
5. After edits, run `after_edit_update.py`.

The high-level equivalent is:

1. `python .agents/skills/zhanggong-impact-blueprint/cig.py analyze --workspace-root . --changed-file <path>`
2. read `next-action.json`
3. edit
4. `python .agents/skills/zhanggong-impact-blueprint/cig.py finish --workspace-root . --test-scope targeted`

## When not to run the full flow

Do not run the full guardian flow for every Markdown file.

Use bypass or lightweight handling for:

- ordinary Markdown notes and summaries
- archives and historical notes
- diagrams and images
- formatting-only edits
- copy-only doc updates that do not change rules, tests, config, schema, or command behavior

## Atlas reading rules

Do not treat `atlas_views` as system decisions.

- `affected_contracts` is the full fact list
- `atlas_views` is the reading layer
- `uncertainty` is a hint layer, not proof
- `DEPENDS_ON` is low-confidence fallback evidence, not a conclusion

If a change touches IPC, event, endpoint, route, component, prop, SQL, env, or config surfaces, read the relevant atlas view before editing.

Recommended reading order:

1. `change_class`
2. `verification_budget`
3. `affected_contracts`
4. `atlas_views`
5. `uncertainty`
6. edit
7. `finish`

## Repeated failure rules

If verification keeps failing:

- do not keep patching the same local function forever
- read `loop_atlas_views` before patching again
- at higher repeat counts, widen the chain instead of only widening tests
- treat `stop_local_patching_reason` as a signal to step back and read across layers

## Guardrails

- Persist only direct edges.
- Never persist indirect or transitive impact as durable graph truth.
- Compute transitive impact only while generating the report.
- GitHub permalink, blame, and compare are optional evidence enhancements, not required dependencies.
- If coverage is unavailable, record that fact. Never fabricate coverage-backed results.
- `tests_passed` must not be described as fully safe.
- Delete actions must move items to the recycle bin or trash by default. Permanent deletion requires explicit, strict user approval first.

## Release hygiene

Before publishing the public skill folder, run:

```bash
python .agents/skills/zhanggong-impact-blueprint/cig.py release-check --workspace-root . --skill-only
```

Do not publish:

- private names or private working-file examples
- absolute user paths
- temp-path leaks
- `config.local.json`
- `.ai/codegraph` runtime artifacts inside the public skill package

## Review Bundle Packaging

- Default external review bundle name: `Stage 13.zip` at the repository root.
- The zip should unpack into a single top-level folder named `Stage 13/`.
- A review bundle must be self-consistent: if it includes `tests/`, it must also include every fixture directory those tests depend on.
- For this repository that means review bundles should include:
  - `.agents/skills/zhanggong-impact-blueprint/`
  - `.zhanggong-impact-blueprint/`
  - `scripts/`
  - `tests/`
  - `examples/`
  - `benchmark/`
  - `README.md`
  - `AGENTS.md`
  - `STAGE13_REVIEW_GUIDE.md`
  - `STAGE13_CHANGELOG.md`
  - `docs/archive/review-2026-04-19.txt`
- Do not omit `benchmark/` when shipping `tests/test_stage9_workflow.py` or any benchmark-driven review/tests.
- Preserve repo-relative paths exactly; do not rewrite config paths inside the bundle just to make the zip smaller.
- Exclude reviewer-irrelevant noise by default:
  - `.git/`
  - `.ai/`
  - `docs/` except files explicitly listed in the required include set above
  - `dist/`
  - `build/`
  - `__pycache__/`
  - `*.pyc`
  - `*.pyo`
  - temporary logs
  - previous zip artifacts
- Fixture contents under `benchmark/` or `examples/` are not noise, even if they contain folders such as `dist/`, `build/`, or `.cache/`; keep them intact.
- After creating the zip, verify that the expected top-level entries are present, especially `benchmark/`, `tests/`, and `.agents/skills/zhanggong-impact-blueprint/`.

