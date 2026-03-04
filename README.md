# The Document Intelligence Refinery (Interim Submission)

This repository contains the Phase 1 and 2 implementation for a 5-stage agentic pipeline designed to extract structured data from unstructured enterprise documents.

## Architectural Highlights
- **Confidence-Gated Routing:** The `ExtractionRouter` prevents hallucination loops by dropping to higher-tier, more expensive Vision Language Models ONLY if fast-text heuristics fail.
- **Pydantic Driven:** Every stage communicates purely through strictly typed schemas (`DocumentProfile`, `ExtractedDocument`).
- **Externalized Constitution:** Thresholds and guardrails are read from `rubric/extraction_rules.yaml`.
- **Interim Artifact Generator:** `src/run_corpus.py` generates 12 required profiles (3 per class), extraction outputs, and ledger entries.

## Project Structure
```text
├── DOMAIN_NOTES.md                  # Phase 0 Strategic Documentation
├── pyproject.toml                   # Project dependencies
├── rubric/
│   └── extraction_rules.yaml        # External configuration
├── .refinery/
│   ├── profiles/                    # Generated DocumentProfiles (JSON)
│   ├── extractions/                 # Normalized extraction outputs (JSON)
│   └── extraction_ledger.jsonl      # Audit trail of extraction costs & routing
├── tests/
│   └── test_triage.py               # Unit testing
└── src/
    ├── models/                      # Core Pydantic schemas
    ├── agents/                      # Triage and Router Agents
    ├── strategies/                  # Tier A, B, C Extraction strategies
    └── run_corpus.py                # Batch generation script
```

## Setup & Running
1.  **Environment Setup**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -e .
    ```

2.  **Generate Corpus Artifacts**
    Run the generation script. This produces 12 profiles (3 per class), extraction JSON files, and ledger entries.
    ```bash
    python -m src.run_corpus --clean
    ```
    Optional environment variables:
    - `OPENROUTER_API_KEY`: enables live vision extraction calls in Strategy C.
    - `OPENROUTER_VISION_MODEL`: optional model override.
    - `REFINERY_RULES_PATH`: alternate rules YAML path.

3.  **Run Pipeline Tests**
    ```bash
    pytest -q
    ```
