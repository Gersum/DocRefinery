import pytest

from src.agents.chunker import ChunkValidationError, ChunkValidator, ChunkingEngine
from src.agents.fact_table import FactTableExtractor
from src.agents.indexer import PageIndexBuilder, PageIndexNavigator, RetrievalBenchmark
from src.agents.query_agent import QueryAgent
from src.agents.vector_store import LocalVectorStore
from src.models.extraction import BoundingBox, ExtractedDocument, ExtractedPage, ExtractedTable, ExtractedText
from src.models.ldu import ChunkType, LDU


def _sample_extracted_document() -> ExtractedDocument:
    return ExtractedDocument(
        document_id="doc-1",
        pages=[
            ExtractedPage(
                page_num=1,
                text_blocks=[
                    ExtractedText(
                        text="1. First item\n2. Second item\nsee Table 1 for details",
                        page_num=1,
                        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=120),
                    ),
                    ExtractedText(
                        text="Revenue: $4.2B",
                        page_num=1,
                        bbox=BoundingBox(x0=0, y0=130, x1=100, y1=150),
                    ),
                ],
                tables=[
                    ExtractedTable(
                        table_id="tbl-1",
                        page_num=1,
                        headers=["Year", "Revenue"],
                        data=[["2024", "$4.2B"]],
                        bbox=BoundingBox(x0=10, y0=200, x1=200, y1=260),
                    )
                ],
                strategy_used="Strategy B - LayoutExtractor",
            )
        ],
    )


def test_chunking_engine_emits_validated_ldus_with_content_hash():
    chunker = ChunkingEngine()
    ldus = chunker.chunk_document(_sample_extracted_document())

    assert ldus
    assert all(len(ldu.content_hash) >= 16 for ldu in ldus)
    table_ldu = next(ldu for ldu in ldus if ldu.chunk_type == ChunkType.TABLE)
    assert table_ldu.metadata["table_integrity"] == "header_attached"
    assert table_ldu.parent_section == "Page 1"
    assert table_ldu.parent_ldu_id is not None

    text_ldu = next(ldu for ldu in ldus if "see Table 1" in ldu.content)
    assert "table:1" in text_ldu.metadata["cross_references"]


def test_chunking_engine_split_list_respects_rule_3_with_original_token_count(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("retrieval_preferences:\n  chunk_max_tokens: 10\n", encoding="utf-8")

    long_numbered_lines = [f"{i}. item token token token" for i in range(1, 15)]
    long_numbered_text = "\n".join(long_numbered_lines)

    extracted = ExtractedDocument(
        document_id="doc-long-list",
        pages=[
            ExtractedPage(
                page_num=1,
                text_blocks=[
                    ExtractedText(
                        text=long_numbered_text,
                        page_num=1,
                        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=120),
                    )
                ],
                strategy_used="Strategy B - LayoutExtractor",
            )
        ],
    )

    chunker = ChunkingEngine(rules_path=str(rules))
    ldus = chunker.chunk_document(extracted)

    list_ldus = [ldu for ldu in ldus if ldu.chunk_type == ChunkType.LIST]
    assert len(list_ldus) > 1
    assert all(ldu.metadata.get("list_integrity") == "split_part" for ldu in list_ldus)
    assert all((ldu.metadata.get("list_original_token_count") or 0) > 10 for ldu in list_ldus)


def test_chunk_validator_catches_constitution_violations():
    validator = ChunkValidator()
    invalid_ldu = LDU(
        ldu_id="bad-table",
        document_id="doc-1",
        content="a|b",
        chunk_type=ChunkType.TABLE,
        page_refs=[1],
        bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10),
        parent_section="Page 1",
        parent_ldu_id="doc-1-p1-section",
        content_hash="abcdef0123456789",
        metadata={},
    )

    with pytest.raises(ChunkValidationError):
        validator.validate([invalid_ldu])


def test_pageindex_navigation_and_precision_benchmark():
    ldus = [
        LDU(
            ldu_id="a",
            document_id="doc-1",
            content="Revenue growth and income statement details",
            chunk_type=ChunkType.TEXT,
            page_refs=[1],
            parent_section="Revenue Section",
            parent_ldu_id="root",
            content_hash="abcdef0123456789",
        ),
        LDU(
            ldu_id="b",
            document_id="doc-1",
            content="Operational notes and governance",
            chunk_type=ChunkType.TEXT,
            page_refs=[2],
            parent_section="Governance Section",
            parent_ldu_id="root",
            content_hash="1234567890abcdef",
        ),
    ]

    page_index = PageIndexBuilder().build("doc-1", ldus)
    navigator = PageIndexNavigator(page_index)
    vector_store = LocalVectorStore()
    vector_store.ingest_ldus(ldus)

    top = navigator.query("revenue", top_k=1)
    assert top and top[0].section_title == "Revenue Section"

    report = RetrievalBenchmark().evaluate(
        topic="revenue",
        relevant_sections={"Revenue Section"},
        navigator=navigator,
        vector_store=vector_store,
        top_k_sections=1,
        top_k_vectors=2,
    )
    assert report.indexed_precision_at_k >= report.naive_precision_at_k


def test_query_agent_returns_provenance_and_audit_mode(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "retrieval_preferences:\n"
        f"  fact_table_db_path: {tmp_path / 'facts.db'}\n"
        "  pageindex_top_k: 3\n"
        "  vector_top_k: 5\n",
        encoding="utf-8",
    )

    ldus = ChunkingEngine(rules_path=str(rules)).chunk_document(_sample_extracted_document())
    page_index = PageIndexBuilder(rules_path=str(rules)).build("doc-1", ldus)
    navigator = PageIndexNavigator(page_index)
    vector_store = LocalVectorStore(rules_path=str(rules))
    vector_store.ingest_ldus(ldus)

    fact_table = FactTableExtractor(rules_path=str(rules))
    ingested = fact_table.ingest_ldus(ldus, document_name="doc.pdf")
    assert ingested > 0

    agent = QueryAgent(
        navigator=navigator,
        vector_store=vector_store,
        fact_table=fact_table,
        rules_path=str(rules),
    )

    answer = agent.answer("What is the revenue value?", document_name="doc.pdf")
    assert answer.audit_status == "verified"
    assert answer.provenance is not None
    assert answer.provenance.content_hash
    assert answer.provenance.bbox is not None

    verified_claim = agent.audit_mode("Revenue", document_name="doc.pdf")
    assert verified_claim.audit_status == "verified"

    unverifiable_claim = agent.audit_mode("zzzzzzzzzz", document_name="doc.pdf")
    assert unverifiable_claim.audit_status == "unverifiable"
    assert unverifiable_claim.provenance is not None
    assert unverifiable_claim.provenance.verification_status.value == "needs_review"
