from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List

from src.config import chunking_constitution, retrieval_preference
from src.models.extraction import ExtractedDocument
from src.models.ldu import ChunkType, LDU


class ChunkValidationError(ValueError):
    pass


@dataclass
class RuleViolation:
    rule_id: str
    message: str


class ChunkValidator:
    """Validates emitted LDUs against the chunking constitution before persistence."""

    def __init__(self, rules_path: str | None = None):
        self.rules = chunking_constitution(rules_path=rules_path)
        self.max_tokens = int(retrieval_preference("chunk_max_tokens", 400, rules_path))

    def validate(self, ldus: List[LDU]) -> None:
        violations: List[RuleViolation] = []
        for ldu in ldus:
            # Rule 1: table content is never emitted without header context.
            if ldu.chunk_type == ChunkType.TABLE and ldu.metadata.get("table_integrity") != "header_attached":
                violations.append(RuleViolation("rule_1", f"{ldu.ldu_id} missing table header binding"))

            # Rule 2: figure caption is required as metadata for figure chunks.
            if ldu.chunk_type == ChunkType.FIGURE and "caption" not in ldu.metadata:
                violations.append(RuleViolation("rule_2", f"{ldu.ldu_id} missing figure caption metadata"))

            # Rule 3: numbered list should remain single chunk unless it exceeds max_tokens.
            if ldu.chunk_type == ChunkType.LIST:
                list_integrity = ldu.metadata.get("list_integrity")
                raw_original_tokens = ldu.metadata.get("list_original_token_count", ldu.token_count)
                try:
                    original_tokens = int(raw_original_tokens)
                except (TypeError, ValueError):
                    original_tokens = ldu.token_count

                if original_tokens <= self.max_tokens and list_integrity != "single":
                    violations.append(RuleViolation("rule_3", f"{ldu.ldu_id} list split before max token threshold"))
                if original_tokens > self.max_tokens and list_integrity not in {"split_part", "single"}:
                    violations.append(RuleViolation("rule_3", f"{ldu.ldu_id} list integrity marker missing"))

            # Rule 4: all non-section chunks carry parent section metadata.
            if not ldu.metadata.get("is_section_parent"):
                if not ldu.parent_section or not ldu.parent_ldu_id:
                    violations.append(RuleViolation("rule_4", f"{ldu.ldu_id} missing parent section linkage"))

            # Rule 5: explicit cross-references are resolved into metadata relationships.
            if re.search(r"\bsee\s+(table|figure|section)\s+\d+\b", ldu.content, flags=re.IGNORECASE):
                if not ldu.metadata.get("cross_references"):
                    violations.append(RuleViolation("rule_5", f"{ldu.ldu_id} cross-reference unresolved"))

        if violations:
            details = "; ".join([f"{v.rule_id}: {v.message}" for v in violations])
            raise ChunkValidationError(details)


class ChunkingEngine:
    """Transforms normalized extraction output into constitution-compliant LDUs."""

    CROSS_REF_PATTERN = re.compile(r"\bsee\s+(table|figure|section)\s+(\d+)\b", flags=re.IGNORECASE)

    def __init__(self, rules_path: str | None = None, validator: ChunkValidator | None = None):
        self.rules_path = rules_path
        self.max_tokens = int(retrieval_preference("chunk_max_tokens", 400, rules_path))
        self.validator = validator or ChunkValidator(rules_path=rules_path)

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _token_count(self, text: str) -> int:
        return len(text.split())

    def _extract_cross_refs(self, text: str) -> List[str]:
        refs = []
        for kind, number in self.CROSS_REF_PATTERN.findall(text):
            refs.append(f"{kind.lower()}:{number}")
        return refs

    def _is_numbered_list(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        numbered = sum(1 for line in lines if re.match(r"^\d+[\.\)]\s+", line))
        return numbered >= 2

    def _split_by_token_window(self, text: str) -> List[str]:
        tokens = text.split()
        if len(tokens) <= self.max_tokens:
            return [text]
        parts = []
        for i in range(0, len(tokens), self.max_tokens):
            parts.append(" ".join(tokens[i : i + self.max_tokens]))
        return parts

    def chunk_document(self, extracted: ExtractedDocument) -> List[LDU]:
        ldus: List[LDU] = []
        for page in extracted.pages:
            section_title = f"Page {page.page_num}"
            section_id = f"{extracted.document_id}-p{page.page_num}-section"
            child_ids: List[str] = []

            for text_idx, block in enumerate(page.text_blocks, start=1):
                chunk_type = ChunkType.LIST if self._is_numbered_list(block.text) else ChunkType.TEXT
                parts = self._split_by_token_window(block.text) if chunk_type == ChunkType.LIST else [block.text]
                full_list_token_count = self._token_count(block.text) if chunk_type == ChunkType.LIST else None
                for part_idx, part in enumerate(parts, start=1):
                    ldu_id = f"{extracted.document_id}-p{page.page_num}-t{text_idx}-{part_idx}"
                    child_ids.append(ldu_id)
                    token_count = self._token_count(part)
                    list_integrity = "single"
                    if chunk_type == ChunkType.LIST and len(parts) > 1:
                        list_integrity = "split_part"

                    ldus.append(
                        LDU(
                            ldu_id=ldu_id,
                            document_id=extracted.document_id,
                            content=part,
                            chunk_type=chunk_type,
                            page_refs=[page.page_num],
                            bounding_box=block.bbox,
                            parent_section=section_title,
                            parent_ldu_id=section_id,
                            child_ldu_ids=[],
                            token_count=token_count,
                            content_hash=self._hash(part),
                            metadata={
                                "source_strategy": page.strategy_used,
                                "list_integrity": list_integrity if chunk_type == ChunkType.LIST else None,
                                "list_original_token_count": full_list_token_count if chunk_type == ChunkType.LIST else None,
                                "cross_references": self._extract_cross_refs(part),
                            },
                        )
                    )

            for table_idx, table in enumerate(page.tables, start=1):
                rows = [" | ".join([str(cell) for cell in row]) for row in table.data]
                table_text = "\n".join(rows).strip()
                if not table_text:
                    continue
                ldu_id = f"{extracted.document_id}-p{page.page_num}-table-{table_idx}"
                child_ids.append(ldu_id)
                ldus.append(
                    LDU(
                        ldu_id=ldu_id,
                        document_id=extracted.document_id,
                        content=table_text,
                        chunk_type=ChunkType.TABLE,
                        page_refs=[page.page_num],
                        bounding_box=table.bbox,
                        parent_section=section_title,
                        parent_ldu_id=section_id,
                        child_ldu_ids=[],
                        token_count=self._token_count(table_text),
                        content_hash=self._hash(table_text),
                        metadata={
                            "table_headers": table.headers or [],
                            "table_integrity": "header_attached",
                            "cross_references": self._extract_cross_refs(table_text),
                        },
                    )
                )

            for fig_idx, figure in enumerate(page.figures, start=1):
                figure_content = figure.caption or f"Figure {fig_idx}"
                ldu_id = f"{extracted.document_id}-p{page.page_num}-figure-{fig_idx}"
                child_ids.append(ldu_id)
                ldus.append(
                    LDU(
                        ldu_id=ldu_id,
                        document_id=extracted.document_id,
                        content=figure_content,
                        chunk_type=ChunkType.FIGURE,
                        page_refs=[page.page_num],
                        bounding_box=figure.bbox,
                        parent_section=section_title,
                        parent_ldu_id=section_id,
                        child_ldu_ids=[],
                        token_count=self._token_count(figure_content),
                        content_hash=self._hash(figure_content),
                        metadata={"caption": figure.caption, "cross_references": self._extract_cross_refs(figure_content)},
                    )
                )

            section_content = f"{section_title} section summary"
            ldus.append(
                LDU(
                    ldu_id=section_id,
                    document_id=extracted.document_id,
                    content=section_content,
                    chunk_type=ChunkType.TEXT,
                    page_refs=[page.page_num],
                    bounding_box=(page.text_blocks[0].bbox if page.text_blocks and page.text_blocks[0].bbox else None),
                    parent_section=None,
                    parent_ldu_id=None,
                    child_ldu_ids=child_ids,
                    token_count=self._token_count(section_content),
                    content_hash=self._hash(section_content),
                    metadata={"is_section_parent": True, "section_title": section_title},
                )
            )

        self.validator.validate(ldus)
        return ldus
