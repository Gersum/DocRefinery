import argparse
import json
from pathlib import Path
from typing import Dict

from src.agents.chunker import ChunkingEngine
from src.agents.extractor import ExtractionRouter
from src.agents.fact_table import FactTableExtractor
from src.agents.indexer import PageIndexBuilder, PageIndexNavigator, RetrievalBenchmark
from src.agents.query_agent import QueryAgent
from src.agents.structure_builder import StructureBuilder
from src.agents.triage import TriageAgent
from src.agents.vector_store import build_vector_store
from src.config import retrieval_preference
from src.models.ldu import LDU


INTERIM_DOC_PLAN: Dict[str, str] = {
    # Class A (Annual Financial Report - native digital)
    "CBE_Annual_Report_Part_1": "CBE ANNUAL REPORT 2023-24.pdf",
    "CBE_Annual_Report_Part_2": "CBE Annual Report 2018-19.pdf",
    "CBE_Annual_Report_Part_3": "Annual_Report_JUNE-2023.pdf",
    # Class B (Scanned Government/Legal)
    "DBE_Audit_Report_Part_1": "Audit Report - 2023.pdf",
    "DBE_Audit_Report_Part_2": "2018_Audited_Financial_Statement_Report.pdf",
    "DBE_Audit_Report_Part_3": "2019_Audited_Financial_Statement_Report.pdf",
    # Class C (Technical Assessment Report - mixed)
    "FTA_Performance_Survey_Part_1": "fta_performance_survey_final_report_2022.pdf",
    "FTA_Performance_Survey_Part_2": "Security_Vulnerability_Disclosure_Standard_Procedure_1.pdf",
    "FTA_Performance_Survey_Part_3": "20191010_Pharmaceutical-Manufacturing-Opportunites-in-Ethiopia_VF.pdf",
    # Class D (Structured Data Report - table heavy)
    "Tax_Expenditure_Ethiopia_Part_1": "tax_expenditure_ethiopia_2021_22.pdf",
    "Tax_Expenditure_Ethiopia_Part_2": "Consumer Price Index July 2025.pdf",
    "Tax_Expenditure_Ethiopia_Part_3": "Consumer Price Index August 2025.pdf",
}

DOC_CLASS_QUERY_PACK: Dict[str, list[str]] = {
    "class_a": [
        "What does this report say about revenue or income?",
        "Summarize the key financial highlights.",
        "Which section discusses performance highlights?",
    ],
    "class_b": [
        "What audit opinion or finding is stated?",
        "Summarize the main compliance statements.",
        "Which part of the document references financial statements?",
    ],
    "class_c": [
        "What are the major assessment findings?",
        "Which section describes implementation challenges?",
        "Summarize recommendations from the report.",
    ],
    "class_d": [
        "What tax expenditure values are reported?",
        "Which sections contain fiscal category tables?",
        "Summarize the key multi-year numerical trends.",
    ],
}

DOC_CLASS_BENCH_TOPIC: Dict[str, str] = {
    "class_a": "financial performance revenue income statement",
    "class_b": "audit opinion compliance findings",
    "class_c": "assessment findings recommendations implementation",
    "class_d": "tax expenditure fiscal table values",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate interim profiles and extraction ledger.")
    parser.add_argument("--corpus-dir", default="corpus", help="Directory containing PDF corpus.")
    parser.add_argument("--rules-path", default="rubric/extraction_rules.yaml", help="Extraction configuration YAML.")
    parser.add_argument("--clean", action="store_true", help="Clean existing profile and extraction artifacts first.")
    return parser.parse_args()


def ensure_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required corpus file not found: {path}")


def infer_doc_class(profile_id: str) -> str:
    if profile_id.startswith("CBE_Annual_Report"):
        return "class_a"
    if profile_id.startswith("DBE_Audit_Report"):
        return "class_b"
    if profile_id.startswith("FTA_Performance_Survey"):
        return "class_c"
    return "class_d"


def infer_relevant_sections(ldus: list[LDU], topic: str) -> set[str]:
    topic_tokens = {token for token in topic.lower().split() if token}
    matched_sections = set()
    for ldu in ldus:
        if not ldu.parent_section:
            continue
        content_tokens = set(ldu.content.lower().split())
        if topic_tokens.intersection(content_tokens):
            matched_sections.add(ldu.parent_section)

    if matched_sections:
        return matched_sections

    first_section = next((ldu.parent_section for ldu in ldus if ldu.parent_section), "Document")
    return {first_section}


def clean_artifacts(
    profiles_dir: Path,
    extractions_dir: Path,
    structures_dir: Path,
    pageindex_dir: Path,
    query_examples_dir: Path,
    retrieval_dir: Path,
    ledger_path: Path,
    review_queue_path: Path,
    fact_db_path: Path,
) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    extractions_dir.mkdir(parents=True, exist_ok=True)
    structures_dir.mkdir(parents=True, exist_ok=True)
    pageindex_dir.mkdir(parents=True, exist_ok=True)
    query_examples_dir.mkdir(parents=True, exist_ok=True)
    retrieval_dir.mkdir(parents=True, exist_ok=True)
    for target_dir in [profiles_dir, extractions_dir, structures_dir, pageindex_dir, query_examples_dir, retrieval_dir]:
        for item in target_dir.glob("*.json"):
            item.unlink()
    if ledger_path.exists():
        ledger_path.unlink()
    if review_queue_path.exists():
        review_queue_path.unlink()
    if fact_db_path.exists():
        fact_db_path.unlink()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    corpus_dir = (root / args.corpus_dir).resolve()
    profiles_dir = root / ".refinery" / "profiles"
    extractions_dir = root / ".refinery" / "extractions"
    structures_dir = root / ".refinery" / "structures"
    pageindex_dir = root / ".refinery" / "pageindex"
    query_examples_dir = root / ".refinery" / "query_examples"
    retrieval_dir = root / ".refinery" / "retrieval_benchmark"
    ledger_path = root / ".refinery" / "extraction_ledger.jsonl"
    review_queue_path = root / ".refinery" / "review_queue.jsonl"
    fact_db_path = root / str(retrieval_preference("fact_table_db_path", ".refinery/facts.db", args.rules_path))

    if args.clean:
        clean_artifacts(
            profiles_dir,
            extractions_dir,
            structures_dir,
            pageindex_dir,
            query_examples_dir,
            retrieval_dir,
            ledger_path,
            review_queue_path,
            fact_db_path,
        )
    else:
        profiles_dir.mkdir(parents=True, exist_ok=True)
        extractions_dir.mkdir(parents=True, exist_ok=True)
        structures_dir.mkdir(parents=True, exist_ok=True)
        pageindex_dir.mkdir(parents=True, exist_ok=True)
        query_examples_dir.mkdir(parents=True, exist_ok=True)
        retrieval_dir.mkdir(parents=True, exist_ok=True)

    triage = TriageAgent(sample_pages=5, rules_path=args.rules_path)
    router = ExtractionRouter(ledger_path=str(ledger_path), rules_path=args.rules_path)
    chunker = ChunkingEngine(rules_path=args.rules_path)
    index_builder = PageIndexBuilder(rules_path=args.rules_path)
    fact_table = FactTableExtractor(rules_path=args.rules_path)
    structurer = StructureBuilder()
    benchmarker = RetrievalBenchmark()

    processed = 0
    for profile_id, filename in INTERIM_DOC_PLAN.items():
        pdf_path = corpus_dir / filename
        ensure_file_exists(pdf_path)

        print(f"Processing {profile_id} from {filename} ...")
        doc_class = infer_doc_class(profile_id)
        profile = triage.profile_document(str(pdf_path), profile_id)
        extracted = router.execute_extraction(str(pdf_path), profile)
        ldus = chunker.chunk_document(extracted)
        page_index = index_builder.build(profile_id, ldus)
        provenance_chains = structurer.build_provenance_chains(extracted, filename, ldus)
        vector_store = build_vector_store(rules_path=args.rules_path)
        vector_store.ingest_ldus(ldus)
        navigator = PageIndexNavigator(page_index)
        query_agent = QueryAgent(navigator=navigator, vector_store=vector_store, fact_table=fact_table, rules_path=args.rules_path)

        fact_count = fact_table.ingest_ldus(ldus, document_name=filename)
        benchmark_topic = DOC_CLASS_BENCH_TOPIC[doc_class]
        relevant_sections = infer_relevant_sections(ldus, benchmark_topic)
        benchmark_report = benchmarker.evaluate(
            topic=benchmark_topic,
            relevant_sections=relevant_sections,
            navigator=navigator,
            vector_store=vector_store,
        )

        query_results = []
        for question in DOC_CLASS_QUERY_PACK[doc_class]:
            response = query_agent.answer(question=question, document_name=filename)
            query_results.append(
                {
                    "question": question,
                    "answer": response.answer,
                    "audit_status": response.audit_status,
                    "tool_trace": response.tool_trace,
                    "provenance": response.provenance.model_dump(mode="json") if response.provenance else None,
                }
            )
        audit_claim = f"{benchmark_topic} is explicitly discussed in this document."
        audit_response = query_agent.audit_mode(claim=audit_claim, document_name=filename)

        (profiles_dir / f"{profile_id}.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        (extractions_dir / f"{profile_id}.json").write_text(extracted.model_dump_json(indent=2), encoding="utf-8")
        (pageindex_dir / f"{profile_id}.json").write_text(
            page_index.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (query_examples_dir / f"{profile_id}.json").write_text(
            json.dumps(
                {
                    "document_id": profile_id,
                    "document_class": doc_class,
                    "queries": query_results,
                    "audit_mode": {
                        "claim": audit_claim,
                        "result": audit_response.answer,
                        "audit_status": audit_response.audit_status,
                        "tool_trace": audit_response.tool_trace,
                        "provenance": (
                            audit_response.provenance.model_dump(mode="json")
                            if audit_response.provenance
                            else None
                        ),
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (retrieval_dir / f"{profile_id}.json").write_text(
            json.dumps(
                {
                    "document_id": profile_id,
                    "topic": benchmark_topic,
                    "relevant_sections": sorted(relevant_sections),
                    "naive_precision_at_k": benchmark_report.naive_precision_at_k,
                    "indexed_precision_at_k": benchmark_report.indexed_precision_at_k,
                    "naive_hits": benchmark_report.naive_hits,
                    "indexed_hits": benchmark_report.indexed_hits,
                    "top_sections": benchmark_report.top_sections,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (structures_dir / f"{profile_id}.json").write_text(
            json.dumps(
                {
                    "document_id": profile_id,
                    "ldus": [ldu.model_dump(mode="json") for ldu in ldus],
                    "page_index": page_index.model_dump(mode="json"),
                    "provenance_chains": [chain.model_dump(mode="json") for chain in provenance_chains],
                    "fact_count": fact_count,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        processed += 1

    print(f"Completed artifact generation for {processed} documents.")


if __name__ == "__main__":
    main()
