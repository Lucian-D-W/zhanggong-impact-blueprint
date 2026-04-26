# CLI Output Contract

Stage 21 separates terminal brevity from machine detail.

## Analyze Brief

Default `analyze` terminal output is a 12-20 line summary. It should show:

- `selected_seed`
- `secondary_seeds` when present
- `workflow_lane`
- `verification_budget`
- `recommended_test_scope`
- `graph_provider`, `provider_effective`, `provider_authority`, and `provider_status`
- first `must_read_first` paths
- top uncertainty
- next step
- paths to report, next-action, facts, and inferences

Use `--json`, `--verbose-json`, or `--full-json` when scripts need the full payload.

## Summary Layer

Path: `.ai/codegraph/summary.json`

Purpose: first-glance conclusion for humans and agents.

Contains:

- selected seed and secondary seeds
- workflow lane
- verification budget and test scope
- must-read paths
- top uncertainty
- next step
- provider status and authority
- overall trust

## Facts Layer

Path: `.ai/codegraph/facts.json`

Purpose: observed repo state only.

Contains:

- command and task id
- changed files and changed lines
- selected seed and secondary seeds
- provider status, authority, reason, and fallback reason when internal took over
- build facts
- test result facts when available
- final state when available

## Inferences Layer

Path: `.ai/codegraph/inferences.json`

Purpose: interpretation, uncertainty, fallback, and low-confidence evidence.

Contains:

- seed reason and candidate seeds
- fallback explanation split into provider fallback and seed/context fallback
- budget reason codes
- report completeness
- test signal interpretation
- trust axes and trust explanation
- low-confidence contract relations
- uncertainty hints

## Next Action

Path: `.ai/codegraph/next-action.json`

Purpose: agent control plane.

It must point to the same summary/facts/inferences and include the actionable next command.
For multi-entry changes it must expose primary seed plus secondary seeds.

## Handoff

Path: `.ai/codegraph/handoff/latest.md`

Purpose: final human-readable transfer note after `finish`.

It should derive from final state and test results. It should not contradict `test-results.json`.

## Test Scope Semantics

Default `finish` verification is current-task verification.

- Directly mapped tests are current-task tests.
- Explicit `--test-command` is current-task evidence because the caller chose it for this task.
- Broad Python `unittest discover -s tests -p test_*.py` is historical/baseline evidence, not current-task evidence.
- When no current-task test is mapped, broad discover should be skipped by default and reported as `effective_test_scope=skipped`.
- Use `--test-scope full` when the user or agent intentionally wants broad baseline verification.

## Final State

Path: `.ai/codegraph/final-state.json`

Purpose: shared final outcome used by handoff, next-action, and test-results.

Contains:

- task status
- tests passed
- effective test scope
- baseline status
- current status
- regression status
- last error when present

## Provider Authority

GitNexus-first does not mean GitNexus owns the workflow. The contract is:

- `graph_provider`: configured preferred graph provider, usually `gitnexus`
- `provider_effective`: provider that actually supplied graph facts for this run
- `provider_authority`: `primary`, `fallback`, `delegated`, or `unavailable`
- `provider_role`: always `fact_source`
- `workflow_owner`: always `zhanggong`

When `provider_authority=primary` and `provider_effective=gitnexus`, internal/default graph language must not mask GitNexus evidence.
When zhanggong falls back to internal, `provider_fallback_reason` must explain the GitNexus problem explicitly.

## Trust Axes

Trust is an explanation, not only a label. The required axes are:

- `graph_freshness`
- `workspace_noise`
- `dependency_confidence`
- `context_confidence`
- `test_signal`
- `overall_trust`

Positive axes must not be used as downgrade reasons. If graph freshness is good but overall trust is low,
the explanation must name the actual lowering axis, such as missing context or no test signal.
