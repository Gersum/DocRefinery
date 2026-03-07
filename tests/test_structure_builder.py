from src.agents.structure_builder import StructureBuilder
from src.models.extraction import BoundingBox, ExtractedDocument, ExtractedPage, ExtractedTable, ExtractedText


def test_structure_builder_generates_ldu_index_and_provenance():
    doc = ExtractedDocument(
        document_id="doc-1",
        pages=[
            ExtractedPage(
                page_num=1,
                text_blocks=[
                    ExtractedText(
                        text="Revenue increased by 10 percent",
                        page_num=1,
                        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
                    )
                ],
                tables=[
                    ExtractedTable(
                        table_id="t1",
                        page_num=1,
                        headers=["Year", "Revenue"],
                        data=[["2024", "10"]],
                        bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
                    )
                ],
            )
        ],
    )

    builder = StructureBuilder()
    ldus = builder.build_ldus(doc)
    page_index = builder.build_page_index(doc)
    chains = builder.build_provenance_chains(doc, "sample.pdf", ldus)

    assert any(ldu.parent_section == "Page 1" for ldu in ldus)
    assert any(ldu.parent_ldu_id and ldu.parent_ldu_id.endswith("-section") for ldu in ldus if ldu.parent_ldu_id)
    assert page_index.root_node.child_sections[0].section_title == "Page 1"
    assert chains[0].document_name == "sample.pdf"
    assert chains[0].page_number == 1
    assert len(chains[0].content_hash) >= 16
