# SAS — Semantic Alignment Score

```
SAS = 0.5 * entity_overlap
    + 0.3 * action_consistency
    + 0.2 * temporal_alignment
```

All three sub-scores in [0, 1]; SAS in [0, 1].

- **entity_overlap** — Jaccard of touched scopes (action-suffix-stripped)
- **action_consistency** — `1 - 0.5 * total_variation(tools_a, tools_b)`
- **temporal_alignment** — `overlap_ms / union_ms` of the two agents' event windows

A pair with SAS < 0.3 AND non-zero entity overlap is flagged as a **drift warning** in the audit summary.

Computed by `synapse.audit.compute_sas(events)` on every audit run. See [the SCF prior art](../prior-art/scf.md) for the algorithm's origin.
