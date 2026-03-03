# The Document Intelligence Refinery (Interim Submission)

This repository contains the Phase 1 & 2 scaffolding for a 5-stage agentic pipeline designed to extract structured data from unstructured enterprise documents.

## Architectural Highlights
- **Confidence-Gated Routing:** The `ExtractionRouter` prevents hallucination loops by dropping to higher-tier, more expensive Vision Language Models ONLY if fast-text heuristics fail.
- **Pydantic Driven:** Every stage communicates purely through strictly typed schemas (`DocumentProfile`, `ExtractedDocument`).
- **Externalized Constitution:** Document parsing rules are isolated in `rubric/extraction_rules.yaml`.

## Project Structure
```text
├── DOMAIN_NOTES.md                  # Phase 0 Strategic Documentation
├── pyproject.toml                   # Locked Dependencies
├── rubric/
│   └── extraction_rules.yaml        # External configuration
├── .refinery/
│   ├── profiles/                    # Generated DocumentProfiles (JSON)
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
    # Or install dependencies manually if hatch project structuring fails
    pip install pydantic pdfplumber PyYAML pytest pytest-mock
    ```

2.  **Generate Corpus Artifacts**
    Run the generation script. It will scan for local PDF files or generate mock profiles representing the 4 required document classes if the original binaries are not present.
    ```bash
    export PYTHONPATH=$(pwd)
    python3 src/run_corpus.py
    ```

3.  **Run Pipeline Tests**
    ```bash
    export PYTHONPATH=$(pwd)
    pytest tests/
    ```
