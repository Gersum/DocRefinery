from __future__ import annotations

import hashlib
from typing import List

from src.models.extraction import BoundingBox, ExtractedDocument, ExtractedText
from src.models.indexing import PageIndex, PageIndexNode, ProvenanceChain, ProvenanceCitation
from src.models.ldu import ChunkType, LDU


class StructureBuilder:
    """Builds LDU, PageIndex, and ProvenanceChain artifacts from normalized extraction output."""

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _default_bbox(self, page_num: int, page_text: List[ExtractedText]) -> BoundingBox:
        if page_text and page_text[0].bbox:
            return page_text[0].bbox
        # Fallback bbox only when page-level geometry is absent.
        return BoundingBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)

    def build_ldus(self, extracted: ExtractedDocument) -> List[LDU]:
        ldus: List[LDU] = []
        for page in extracted.pages:
            section_id = f"{extracted.document_id}-p{page.page_num}-section"
            child_ids: List[str] = []

            for idx, block in enumerate(page.text_blocks, start=1):
                ldu_id = f"{extracted.document_id}-p{page.page_num}-t{idx}"
                child_ids.append(ldu_id)
                ldus.append(
                    LDU(
                        ldu_id=ldu_id,
                        document_id=extracted.document_id,
                        content=block.text,
                        chunk_type=ChunkType.TEXT,
                        page_refs=[page.page_num],
                        bounding_box=block.bbox,
                        parent_section=f"Page {page.page_num}",
                        parent_ldu_id=section_id,
                        token_count=len(block.text.split()),
                        content_hash=self._hash(block.text),
                    )
                )

            for idx, table in enumerate(page.tables, start=1):
                flattened = "\n".join([" | ".join(row) for row in table.data])
                if not flattened.strip():
                    continue
                ldu_id = f"{extracted.document_id}-p{page.page_num}-tb{idx}"
                child_ids.append(ldu_id)
                ldus.append(
                    LDU(
                        ldu_id=ldu_id,
                        document_id=extracted.document_id,
                        content=flattened,
                        chunk_type=ChunkType.TABLE,
                        page_refs=[page.page_num],
                        bounding_box=table.bbox,
                        parent_section=f"Page {page.page_num}",
                        parent_ldu_id=section_id,
                        token_count=len(flattened.split()),
                        content_hash=self._hash(flattened),
                        metadata={"headers": table.headers or []},
                    )
                )

            section_content = f"Page {page.page_num} summary"
            ldus.append(
                LDU(
                    ldu_id=section_id,
                    document_id=extracted.document_id,
                    content=section_content,
                    chunk_type=ChunkType.TEXT,
                    page_refs=[page.page_num],
                    bounding_box=self._default_bbox(page.page_num, page.text_blocks),
                    parent_section=None,
                    child_ldu_ids=child_ids,
                    token_count=len(section_content.split()),
                    content_hash=self._hash(section_content),
                    metadata={"is_section_parent": True},
                )
            )

        return ldus

    def build_page_index(self, extracted: ExtractedDocument) -> PageIndex:
        if not extracted.pages:
            root = PageIndexNode(section_title="Document Root", page_start=1, page_end=1, summary="Empty extraction")
            return PageIndex(document_id=extracted.document_id, root_node=root)

        child_nodes = [
            PageIndexNode(
                section_title=f"Page {page.page_num}",
                page_start=page.page_num,
                page_end=page.page_num,
                summary=f"Extracted items: text={len(page.text_blocks)}, tables={len(page.tables)}, figures={len(page.figures)}",
            )
            for page in extracted.pages
        ]
        root = PageIndexNode(
            section_title="Document Root",
            page_start=extracted.pages[0].page_num,
            page_end=extracted.pages[-1].page_num,
            summary="Auto-generated page hierarchy from extraction output.",
            child_sections=child_nodes,
        )
        return PageIndex(document_id=extracted.document_id, root_node=root)

    def build_provenance_chains(self, extracted: ExtractedDocument, document_name: str, ldus: List[LDU]) -> List[ProvenanceChain]:
        chains: List[ProvenanceChain] = []
        for ldu in ldus:
            page_number = ldu.page_refs[0]
            citation = ProvenanceCitation(
                document_name=document_name,
                document_id=ldu.document_id,
                page_number=page_number,
                excerpt=ldu.content[:160] if ldu.content else None,
                bbox=ldu.bounding_box,
            )
            chains.append(
                ProvenanceChain(
                    document_name=document_name,
                    page_number=page_number,
                    citations=[citation],
                    bbox=ldu.bounding_box,
                    content_hash=ldu.content_hash,
                )
            )
        return chains
