# The Document Intelligence Refinery

This repository implements a five-stage document refinery pipeline for heterogeneous PDFs:
1. Triage Agent (`DocumentProfile`)
2. Confidence-gated multi-strategy extraction router (A -> B -> C escalation)
3. Semantic chunking with rule validation + content hashing
4. PageIndex construction and retrieval pre-navigation
5. Query + provenance + structured fact lookup + audit mode

## What is Implemented

### Core Models (`src/models/`)
- `DocumentProfile`
- `ExtractedDocument`
- `LDU` (includes `content_hash`, `bounding_box`, parent/child chunk relations)
- `PageIndex` / recursive `PageIndexNode`
- `ProvenanceChain` / `ProvenanceCitation` (typed `BoundingBox`, `content_hash`)

### Agents and Strategies
- `src/agents/triage.py`
  - Origin and layout classification
  - Config-driven domain keyword classifier (pluggable strategy)
- `src/agents/extractor.py`
  - Initial strategy from profile
  - Confidence gates from config
  - Escalation A -> B -> C
  - Decision logging + review queue flagging
- `src/strategies/`
  - `FastTextExtractor` (Strategy A)
  - `LayoutExtractor` (Strategy B)
  - `VisionExtractor` (Strategy C, OpenRouter + budget guard)
- `src/agents/chunker.py`
  - `ChunkingEngine` + `ChunkValidator` enforcing 5 chunking rules
- `src/agents/indexer.py`
  - `PageIndexBuilder` with cheap summary generation (OpenRouter when available, heuristic fallback)
  - `PageIndexNavigator` for top-k section routing
  - Precision benchmark (`naive` vs `PageIndex`-guided retrieval)
- `src/agents/vector_store.py`
  - Local vector ingestion/retrieval
  - Configurable backend (`local_hash`, optional `chroma`)
- `src/agents/fact_table.py`
  - Numeric/key-value fact extraction to SQLite
- `src/agents/query_agent.py`
  - Tools: `pageindex_navigate`, `semantic_search`, `structured_query`
  - Answer output with `ProvenanceChain`
  - `audit_mode` for verify-or-unverifiable behavior

## Configuration

All major tunables are externalized in [`rubric/extraction_rules.yaml`](/Users/gersumasfaw/Downloads/week3/rubric/extraction_rules.yaml):
- extraction thresholds and confidence gates
- domain keyword lists
- chunking constitution
- retrieval preferences (chunk limits, vector backend, PageIndex/semantic top-k, fact DB path)

To onboard a new domain, edit only `domain_keywords` in YAML; no code changes are required.

## Setup (Under 10 Minutes)

```bash
cd /Users/gersumasfaw/Downloads/week3
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

Optional environment variables:
- `OPENROUTER_API_KEY` for Strategy C VLM calls and LLM summaries
- `OPENROUTER_VISION_MODEL` to pin a vision model
- `REFINERY_RULES_PATH` to point to an alternate rules file

## Run the Corpus Pipeline

```bash
cd /Users/gersumasfaw/Downloads/week3
set -a && source .env && set +a
./venv/bin/python -m src.run_corpus --clean
```

This generates:
- `.refinery/profiles/*.json`
- `.refinery/extractions/*.json`
- `.refinery/extraction_ledger.jsonl`
- `.refinery/review_queue.jsonl`
- `.refinery/structures/*.json`
- `.refinery/pageindex/*.json`
- `.refinery/retrieval_benchmark/*.json`
- `.refinery/query_examples/*.json`
- `.refinery/facts.db`

## Run Tests

```bash
cd /Users/gersumasfaw/Downloads/week3
./venv/bin/python -m pytest -q
```

## Evidence Paths for Rubric Review

- Routing decisions: `.refinery/extraction_ledger.jsonl`
- Low-confidence review flags: `.refinery/review_queue.jsonl`
- LDU/PageIndex/Provenance artifacts: `.refinery/structures/`
- PageIndex trees: `.refinery/pageindex/`
- Retrieval precision comparison: `.refinery/retrieval_benchmark/`
- Query + provenance + audit outputs: `.refinery/query_examples/`
