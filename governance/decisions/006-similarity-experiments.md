# DR-006: Similarity Experiments

Status: provisional-local-reference

Date: 2026-05-13

## Context

OpenABM needs semantic trace similarity and behavior-discovery clustering, but
the initial implementation must preserve provenance and remain self-hostable.
Similarity should help investigations find related traces without becoming an
opaque decision layer or a hidden production vector-store commitment.

## Contract

Similarity implementations must expose:

- explicit representation versions;
- provider, model, dimension, and source-hash metadata;
- deterministic search/ranking output shapes;
- cited trace/span evidence for returned matches;
- fail-closed behavior when embeddings or model-backed ranking are disabled;
- rebuild and inspection paths for local indexed representations;
- replacement behind the same `/v1/search/similar` and similarity-index
  contracts.

## Candidates

- Disabled similarity mode.
- On-demand local-model semantic ranking over bounded candidate traces.
- OpenAI-compatible embedding calls with deterministic cosine ranking.
- SQLite-backed local vector records with transparent rebuild/search.
- Future ANN/vector-store backend after pilot evidence.

## Workloads

- Golden trace fixture similarity.
- Wrong-tool and fabricated-commitment incident cohorts.
- Passive novelty grouping over stored trace embeddings.
- Local LM Studio embedding canaries.
- Search and investigation acceptance tests.

## Decision

Use a layered local reference:

1. Disabled mode remains the fail-closed default when no model or embedding
   provider is configured.
2. On-demand embedding similarity is available when an OpenAI-compatible
   embedding provider is configured.
3. A SQLite-backed similarity index stores trace/span vectors with
   representation versions, source hashes, dimensions, provider, and model
   metadata for transparent local rebuild and search.
4. Passive novelty runs may optionally use stored vectors for candidate grouping,
   but human review remains the promotion gate.

Do not adopt a production ANN/vector-store backend until pilot workloads show
that local JSON vector search misses quality or performance targets.

## Evidence

- Integration tests cover disabled similarity, embedding-backed
  `/v1/search/similar`, similarity-index rebuild/search, and novelty grouping
  with stored vectors.
- Unit tests cover OpenAI-compatible embedding response parsing and fail-closed
  provider behavior.
- `IMPLEMENTATION_PROGRESS.md` records live LM Studio canaries for
  `text-embedding-nomic-embed-text-v1.5` and `qwen3.5-9b-mlx` similarity paths.

## Known Limitations

- SQLite JSON vector search is transparent and easy to audit, but it is not a
  production ANN strategy.
- Broad clustering quality is intentionally review-gated and requires pilot
  evidence before promotion.

## Revisit Triggers

- Pilot trace volume makes local vector search too slow.
- Similarity quality misses investigation acceptance cases.
- Production deployment needs ANN indexing, vector filtering, or hybrid
  retrieval beyond the local reference contract.
- A candidate vector store can satisfy the same provenance, rebuild, export,
  delete, and audit requirements with better workload evidence.
