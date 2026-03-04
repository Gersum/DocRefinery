import pytest
from pydantic import ValidationError

from src.models.extraction import BoundingBox
from src.models.indexing import PageIndexNode, ProvenanceChain, ProvenanceCitation, VerificationStatus
from src.models.ldu import ChunkType, LDU


def test_bounding_box_requires_positive_area():
    with pytest.raises(ValidationError):
        BoundingBox(x0=10, y0=10, x1=5, y1=20)


def test_provenance_chain_uses_typed_bbox_and_hash_at_chain_level():
    citation = ProvenanceCitation(document_name="Doc", document_id="d1", page_number=3)
    chain = ProvenanceChain(
        citations=[citation],
        bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10),
        content_hash="0123456789abcdef",
        verification_status=VerificationStatus.UNVERIFIED,
    )
    assert chain.bbox is not None
    assert chain.content_hash == "0123456789abcdef"


def test_page_index_node_validates_page_ranges():
    with pytest.raises(ValidationError):
        PageIndexNode(section_title="Section", page_start=5, page_end=4)


def test_ldu_relationship_constraints():
    with pytest.raises(ValidationError):
        LDU(
            ldu_id="ldu-1",
            document_id="doc-1",
            content="sample",
            chunk_type=ChunkType.TEXT,
            page_refs=[1, 1, 2],
            content_hash="abcdef0123456789",
            parent_ldu_id="ldu-1",
        )

    with pytest.raises(ValidationError):
        LDU(
            ldu_id="ldu-2",
            document_id="doc-1",
            content="sample",
            chunk_type=ChunkType.TEXT,
            page_refs=[1],
            content_hash="abcdef0123456789",
            child_ldu_ids=["ldu-2"],
        )
