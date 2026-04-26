# Trust Model

Stage 21 treats trust as explanation across axes, not as a single mysterious score.

## Facts

- Graph provider status is a fact.
- Changed files and selected test command are facts.
- Test pass/fail is a fact.
- Baseline status is a fact.
- Coverage unavailable is a fact.
- A low-confidence `DEPENDS_ON` edge is a fact about uncertain evidence, not proof of precise architecture.

## Inferences

- Seed selection is an inference unless explicitly provided by the user.
- Secondary seeds are bounded context, not proof that every entry was fully covered.
- Verification budget is a policy decision.
- `affected_contracts`, `architecture_chains`, and `atlas_views` are useful views over evidence, not magical proof.
- Fallback is an inference about best continuation path and must include a reason.

## Required Axes

- `graph_freshness`: whether the graph itself is current.
- `workspace_noise`: whether generated/cache files pollute the active context.
- `dependency_confidence`: whether dependency state is known and stable.
- `context_confidence`: whether seed/changed-file context is explicit, inferred, fallback, or missing.
- `test_signal`: whether direct, configured, full, none, or unknown test evidence is available.
- `overall_trust`: the combined trust posture.

Positive axes must not be listed as downgrade reasons. If the graph is fresh but overall trust is low, explain the actual lowering axis such as missing context or no test signal.

## Tests

Do not collapse these statements:

- tests passed
- directly affected tests were found
- coverage is available
- baseline is green

When no directly affected tests are found but tests pass, describe the evidence as a no-regression signal unless targeted coverage is actually proven.

## Never Say

- safe just because tests passed
- covered when coverage is unavailable
- complete when context is partial or fallback was used
- high confidence when only low-confidence fallback evidence exists
- this edit broke the suite when baseline/failure signature says the repo was already red
