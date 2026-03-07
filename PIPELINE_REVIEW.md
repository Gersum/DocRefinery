# End-to-End Pipeline Review

This is the full execution flow currently implemented in the project.

## Pipeline Diagram

```mermaid
flowchart TD
    A[PDF from corpus/] --> B[run_corpus.py]

    B --> C[TriageAgent]
    C --> C1[Profile metrics via pdfplumber\nchar density, image ratio, tables, columns, language]
    C1 --> C2[DocumentProfile\norigin_type, layout_complexity, domain_hint, estimated_extraction_cost]

    C2 --> D[ExtractionRouter]
    D --> D0{Initial strategy by cost}
    D0 -->|FAST_TEXT_SUFFICIENT| E[Strategy A: FastTextExtractor]
    D0 -->|NEEDS_LAYOUT_MODEL| F[Strategy B: LayoutExtractor]
    D0 -->|NEEDS_VISION_MODEL| G[Strategy C: VisionExtractor]

    F --> F1[Docling path when available\ndocling_parse + DoclingDocumentAdapter]
    F --> F2[Fallback path\npdfplumber-only layout extraction]

    E --> H[Confidence check]
    F --> H
    G --> H

    H -->|below gate from A| F
    H -->|below gate from B| G
    H -->|final low confidence| I[Flag review_required]

    D --> J[Write extraction_ledger.jsonl]
    I --> K[Append review_queue.jsonl]

    E --> L[ExtractedDocument]
    F --> L
    G --> L

    L --> M[ChunkingEngine]
    M --> M1[Generate LDUs\nTEXT/LIST/TABLE/FIGURE + section parents]
    M1 --> M2[ChunkValidator\nconstitution rules 1-5]

    M2 --> N[PageIndexBuilder]
    N --> N1[Section summaries + entities]
    N1 --> O[PageIndexNavigator]

    M2 --> P[FactTableExtractor]
    P --> P1[Store numeric/key-value facts in SQLite\n.refinery/facts.db]

    M2 --> Q[VectorStore]
    Q --> Q1[local_hash or chroma backend]

    O --> R[QueryAgent]
    P1 --> R
    Q1 --> R
    R --> R1[answer() and audit_mode()\nprovenance + tool_trace + verification status]

    O --> S[RetrievalBenchmark]
    Q1 --> S
    S --> S1[naive vs indexed precision@k]

    B --> T[Artifact Writers]
    C2 --> T
    L --> T
    M2 --> T
    N --> T
    R1 --> T
    S1 --> T

    T --> U[.refinery/profiles/*.json]
    T --> V[.refinery/extractions/*.json]
    T --> W[.refinery/structures/*.json]
    T --> X[.refinery/pageindex/*.json]
    T --> Y[.refinery/query_examples/*.json]
    T --> Z[.refinery/retrieval_benchmark/*.json]
    T --> J
    T --> K
```

## Key Understanding Notes

- The pipeline is **confidence-gated**, not one-shot: strategy escalation is A → B → C when confidence falls below configured thresholds.
- **Docling is used in Strategy B** when `docling_parse` is installed; otherwise Strategy B falls back to pdfplumber.
- The extraction stage produces normalized pages; the retrieval stage is built on top of LDUs, page index, fact table, and vector search.
- Query answering always records tool usage (`pageindex_navigate`, `semantic_search`, `structured_query`) and returns provenance status.
- Rules and thresholds are centralized in `rubric/extraction_rules.yaml` and loaded through `src/config.py`.