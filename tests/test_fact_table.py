import os
import tempfile
import yaml

from src.agents.fact_table import FactTableExtractor
from src.models.ldu import LDU, ChunkType


def test_fact_table_extraction_and_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_path = os.path.join(tmpdir, "rules.yaml")
        db_path = os.path.join(tmpdir, "facts.db")
        rules = {
            "retrieval_preferences": {
                "fact_table_db_path": db_path,
                "fact_min_numeric_length": 1,
            }
        }
        with open(rules_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(rules, fh)

        # Key-value LDU
        kv = LDU(
            ldu_id="l1",
            document_id="doc1",
            content="Revenue: $1,234.56",
            chunk_type=ChunkType.TEXT,
            page_refs=[1],
            bounding_box=None,
            content_hash="x" * 16,
        )

        # Table LDU
        table = LDU(
            ldu_id="l2",
            document_id="doc1",
            content="Revenue | 1000 | 2000\nCost | 400 | 500",
            chunk_type=ChunkType.TABLE,
            page_refs=[2],
            bounding_box=None,
            content_hash="y" * 16,
            metadata={"table_headers": ["Label", "2023", "2024"]},
        )

        extractor = FactTableExtractor(rules_path=rules_path)
        count = extractor.ingest_ldus([kv, table], document_name="doc1")
        assert count == 5

        results = extractor.query("Revenue", limit=10)
        assert any("Revenue" in r["key"] or r["key"].startswith("Revenue::") for r in results)
