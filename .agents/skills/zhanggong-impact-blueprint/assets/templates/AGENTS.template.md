# ZG Impact Blueprint Working Agreement

This repository uses ZG Impact Blueprint as a low-friction workflow harness.

## Ownership

- `zhanggong` owns the user-facing workflow.
- `GitNexus` is the default primary graph fact source when ready.
- Providers enrich graph/context/impact; they do not own setup, lane choice, test choice, finish, or handoff.
- Internal fallback is acceptable when GitNexus is missing, stale, unindexed, or path-incompatible, as long as the reason is explicit.
- Do not run bare `gitnexus analyze` as the normal path; use zhanggong so side effects are suppressed and provider authority is recorded.

## Lanes

Use the smallest honest lane:

- `bypass`: ordinary docs, archive notes, diagrams, review prose, and other non-runtime/non-rule/non-agent-behavior edits.
- `lightweight`: docs/templates that affect agent or workflow behavior but do not directly change runtime code behavior.
- `full_guardian`: source, tests, config, schema, SQL, env, dependencies, rules, and command behavior.

Run `classify-change --changed-file <path>` when the lane is unclear.

## Full Guardian Protocol

Whenever a task changes code, behavior, configuration, schema, tests, rules, dependencies, API surfaces, routes, events, IPC, SQL, env vars, or config keys:

1. Run `cig.py health` or `cig.py calibrate` if repo readiness, graph provider, or test command choice is unclear.
2. Run `cig.py analyze --changed-file <path>` before editing.
3. Read the brief first, then `.ai/codegraph/next-action.json` if more detail is needed.
4. Read `.ai/codegraph/facts.json` for observed state and `.ai/codegraph/inferences.json` for uncertainty/trust/fallback.
5. Edit.
6. Run `cig.py finish` with the recommended scope.

## Guardrails

- Do not force bypass or lightweight tasks into full guardian unless their content changes rules, setup, tests, commands, config, schema, or runtime behavior.
- Do not claim safety just because tests passed.
- If no directly affected tests were found, say whether passing tests are only a no-regression signal.
- If the baseline is red, distinguish historical baseline reality from a new regression.
- Multi-entry changes should continue with primary seed plus secondary seeds unless the candidate set is truly unconverged.
- Keep low-confidence `DEPENDS_ON`, uncertainty, fallback, and trust explanations separate from high-confidence facts.
- Delete actions must move items to the recycle bin or trash by default. Permanent deletion requires explicit, strict user approval first.
