# Stage 21 - Low-Friction Reality Workflow

Stage 21 refocuses ZG Impact Blueprint from a heavy guardrail into a daily workflow harness.
The goal is not more graph fields, more contracts, or a smarter planner. The goal is lower friction,
better facts, and clearer boundaries in real repositories.

## Core Problem Solved

Users valued the `setup -> health -> analyze -> finish` spine, structured `next-action.json`,
`affected_contracts`, `atlas_views`, and the philosophy that tests passing is not the same as safety.
They did not want every task to feel like an airport security checkpoint.

Stage 21 solves that mismatch by making the workflow explicit about lane, evidence, and uncertainty.

## Product Decisions

- Three lanes are first-class: bypass, lightweight, full guardian.
- `analyze` prints a short executable summary by default.
- Full facts are written to `.ai/codegraph/facts.json`.
- Low-confidence or interpretive material is written to `.ai/codegraph/inferences.json`.
- The daily conclusion is written to `.ai/codegraph/summary.json` and mirrored into `next-action.json`.
- Multi-entry changes default to primary seed plus secondary seeds when the candidate set is workable.
- Hard `selection_required` is reserved for cases where the system truly cannot converge.
- Trust is explained by axes, not by a mysterious score.
- `setup` defaults to minimal and only writes runtime essentials unless `--full` is explicit.

## What Stayed

- `zhanggong` remains the workflow owner.
- GitNexus remains the default primary graph fact source when ready.
- Internal fallback remains valid and explicit, but it cannot silently mask GitNexus.
- `next-action.json` remains the agent-facing control surface.
- `affected_contracts` and `atlas_views` remain available for contract/risk surfaces.
- `finish` remains responsible for test evidence, baseline/regression interpretation, and handoff.

## GitNexus Authority Boundary

GitNexus should be the smoothest path for graph facts, not an implementation detail hidden behind generic report language.

- If GitNexus is ready, `provider_effective=gitnexus` and `provider_authority=primary`.
- If internal is used, `provider_authority=fallback` and `provider_fallback_reason` must say what made GitNexus unavailable.
- Seed fallback is not provider fallback. An inferred/file-level seed may lower context confidence, but it must not be described as GitNexus being unavailable.
- Bare `gitnexus analyze` is not the normal zhanggong workflow because it can write tool-owned guidance into root agent files. zhanggong should invoke GitNexus and suppress those side effects.
- Reports are renderers of provider facts; they do not own graph authority.

## What Got Smaller

- Plain docs can bypass the full guardian flow.
- Workflow/process docs use lightweight flow instead of pretending they are runtime code.
- Source, tests, config, schema, rules, dependencies, and command behavior remain full guardian.
- Default terminal output is a brief, not a JSON excavation site.
- Setup no longer implies full onboarding docs unless explicitly requested.

## Success Criteria

A new user should understand:

- when not to run the workflow,
- when to use lightweight structure,
- when full guardian is required,
- why a seed/test/provider decision was selected,
- what is fact versus inference,
- why tests passing may only mean no obvious regression,
- why a red baseline may not be caused by the current edit.
