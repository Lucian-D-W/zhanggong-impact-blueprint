# Trust Model

## Facts

- Graph nodes and edges are direct-only facts.
- Tests passed is a fact.
- Coverage unavailable is a fact.

## Inference

- Seed selection is an inference.
- App-to-SQL hints may be confirmed edges, high-confidence hints, or metadata only.
- Incremental reuse is a trust decision, not a proof of safety.

## Main fields

- `seed_confidence`: why this seed was selected.
- `graph_trust`: freshness/completeness/build-mode trust for the graph.
- `test_signal`: strength and relevance of the executed test signal.
- `report_completeness`: how complete the current report really is.

## Never say

- "safe" just because tests passed
- "covered" when coverage is unavailable
- "complete" when context is partial or fallback was used

