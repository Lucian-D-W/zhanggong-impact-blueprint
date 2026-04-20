# Trust Model

## Facts

- Graph nodes and edges are direct-only facts.
- Tests passed is a fact.
- Coverage unavailable is a fact.
- A low-confidence `DEPENDS_ON` edge is a fact about uncertain dependency
  evidence, not a proof of precise relationship type.

## Inference

- Seed selection is an inference.
- `affected_contracts` and `architecture_chains` are report views built from
  direct graph evidence; they are useful, but they are not magical proof.
- App-to-SQL hints may be confirmed edges, bounded-confidence links, or
  metadata only.
- Incremental reuse is a trust decision, not a proof of safety.

## Main fields

- `seed_confidence`: why this seed was selected.
- `graph_trust`: freshness/completeness/build-mode trust for the graph.
- `test_signal`: strength and relevance of the executed test signal.
- `report_completeness`: how complete the current report really is.
- `affected_contracts`: contract nodes that were pulled into the current impact
  surface.
- `architecture_chains`: readable contract chains for agent review.

## Never say

- "safe" just because tests passed
- "covered" when coverage is unavailable
- "complete" when context is partial or fallback was used
- "high confidence" when the graph only found a low-confidence `DEPENDS_ON`
  fallback
