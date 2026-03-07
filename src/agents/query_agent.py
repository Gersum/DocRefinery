from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from src.agents.fact_table import FactTableExtractor
from src.agents.indexer import PageIndexNavigator
from src.agents.vector_store import VectorSearchResult, VectorStore
from src.config import retrieval_preference
from src.models.extraction import BoundingBox
from src.models.indexing import ProvenanceChain, ProvenanceCitation, VerificationStatus

try:
    from langgraph.graph import END, StateGraph  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    END = None
    StateGraph = None


@dataclass
class QueryResponse:
    answer: str
    provenance: Optional[ProvenanceChain]
    tool_trace: list[str]
    audit_status: str


class QueryAgent:
    """
    Query agent with three tools:
    - pageindex_navigate
    - semantic_search
    - structured_query
    """

    def __init__(
        self,
        navigator: PageIndexNavigator,
        vector_store: VectorStore,
        fact_table: FactTableExtractor,
        rules_path: str | None = None,
    ):
        self.navigator = navigator
        self.vector_store = vector_store
        self.fact_table = fact_table
        self.pageindex_top_k = int(retrieval_preference("pageindex_top_k", 3, rules_path))
        self.vector_top_k = int(retrieval_preference("vector_top_k", 5, rules_path))

    def pageindex_navigate(self, topic: str) -> list[str]:
        nodes = self.navigator.query(topic, top_k=self.pageindex_top_k)
        return [node.section_title for node in nodes]

    def semantic_search(self, topic: str, allowed_sections: set[str] | None = None) -> list[VectorSearchResult]:
        return self.vector_store.search(topic, top_k=self.vector_top_k, allowed_sections=allowed_sections)

    def structured_query(self, topic: str) -> list[dict]:
        return self.fact_table.query(topic, limit=self.vector_top_k)

    def _provenance_from_semantic_hit(self, hit: VectorSearchResult, document_name: str) -> ProvenanceChain:
        citation = ProvenanceCitation(
            document_name=document_name,
            document_id=hit.document_id,
            page_number=hit.page_refs[0] if hit.page_refs else 1,
            excerpt=hit.content[:180],
            bbox=BoundingBox(**hit.bbox) if hit.bbox and {"x0", "y0", "x1", "y1"}.issubset(hit.bbox.keys()) else None,
        )
        return ProvenanceChain(
            document_name=document_name,
            page_number=citation.page_number,
            citations=[citation],
            bbox=citation.bbox,
            content_hash=hit.content_hash,
            verification_status=VerificationStatus.VERIFIED,
        )

    def _provenance_from_fact(self, fact: dict) -> ProvenanceChain:
        bbox = fact.get("bbox") or {}
        citation = ProvenanceCitation(
            document_name=fact.get("document_name", "unknown"),
            document_id=fact.get("document_id", "unknown"),
            page_number=int(fact.get("page_number", 1)),
            excerpt=f"{fact.get('key')}: {fact.get('value')}",
            bbox=BoundingBox(**bbox) if {"x0", "y0", "x1", "y1"}.issubset((fact.get("bbox") or {}).keys()) else None,
        )
        return ProvenanceChain(
            document_name=citation.document_name,
            page_number=citation.page_number,
            citations=[citation],
            bbox=citation.bbox,
            content_hash=str(fact.get("content_hash", "")) or "missing-content-hash",
            verification_status=VerificationStatus.VERIFIED,
        )

    def _unverifiable_provenance(self, document_name: str, question: str) -> ProvenanceChain:
        return ProvenanceChain(
            document_name=document_name,
            page_number=1,
            citations=[],
            bbox=None,
            content_hash=hashlib.sha256(f"unverifiable:{question}".encode("utf-8")).hexdigest(),
            verification_status=VerificationStatus.NEEDS_REVIEW,
        )

    def answer(self, question: str, document_name: str) -> QueryResponse:
        tool_trace: list[str] = []

        sections = self.pageindex_navigate(question)
        tool_trace.append("pageindex_navigate")
        allowed = set(sections)

        semantic_hits = self.semantic_search(question, allowed_sections=allowed if sections else None)
        tool_trace.append("semantic_search")

        structured_hits = self.structured_query(question)
        tool_trace.append("structured_query")

        numeric_intent = bool(re.search(r"\b(revenue|cost|tax|profit|amount|value|\$|%|\d)\b", question.lower()))
        if numeric_intent and structured_hits:
            fact = structured_hits[0]
            answer = (
                f"{fact.get('key')} = {fact.get('value')} "
                f"(page {fact.get('page_number')})"
            )
            return QueryResponse(
                answer=answer.strip(),
                provenance=self._provenance_from_fact(fact),
                tool_trace=tool_trace,
                audit_status="verified",
            )

        if semantic_hits:
            hit = semantic_hits[0]
            preview = hit.content.strip()
            if len(preview) > 260:
                preview = preview[:257].rstrip() + "..."
            answer = f"{preview} (section: {hit.parent_section or 'n/a'})"
            return QueryResponse(
                answer=answer,
                provenance=self._provenance_from_semantic_hit(hit, document_name=document_name),
                tool_trace=tool_trace,
                audit_status="verified",
            )

        return QueryResponse(
            answer="not found / unverifiable",
            provenance=self._unverifiable_provenance(document_name=document_name, question=question),
            tool_trace=tool_trace,
            audit_status="unverifiable",
        )

    def audit_mode(self, claim: str, document_name: str) -> QueryResponse:
        response = self.answer(claim, document_name=document_name)
        if response.audit_status == "unverifiable":
            return QueryResponse(
                answer="not found / unverifiable",
                provenance=response.provenance,
                tool_trace=response.tool_trace,
                audit_status="unverifiable",
            )
        return QueryResponse(
            answer=response.answer,
            provenance=response.provenance,
            tool_trace=response.tool_trace,
            audit_status="verified",
        )


class LangGraphQueryAgent(QueryAgent):
    """
    LangGraph orchestration wrapper around the same three tools.
    If LangGraph is unavailable, it transparently falls back to QueryAgent.answer.
    """

    def __init__(
        self,
        navigator: PageIndexNavigator,
        vector_store: VectorStore,
        fact_table: FactTableExtractor,
        rules_path: str | None = None,
    ):
        super().__init__(navigator=navigator, vector_store=vector_store, fact_table=fact_table, rules_path=rules_path)
        self._graph = self._build_graph() if StateGraph else None

    def _build_graph(self):
        graph = StateGraph(dict)

        def _navigate(state: dict) -> dict:
            question = state["question"]
            state["sections"] = self.pageindex_navigate(question)
            state.setdefault("tool_trace", []).append("pageindex_navigate")
            return state

        def _semantic(state: dict) -> dict:
            question = state["question"]
            allowed = set(state.get("sections", []))
            state["semantic_hits"] = self.semantic_search(question, allowed_sections=allowed if allowed else None)
            state.setdefault("tool_trace", []).append("semantic_search")
            return state

        def _structured(state: dict) -> dict:
            question = state["question"]
            state["structured_hits"] = self.structured_query(question)
            state.setdefault("tool_trace", []).append("structured_query")
            return state

        def _respond(state: dict) -> dict:
            question = state["question"]
            document_name = state["document_name"]
            response = super(LangGraphQueryAgent, self).answer(question=question, document_name=document_name)
            state["response"] = response
            return state

        graph.add_node("navigate", _navigate)
        graph.add_node("semantic", _semantic)
        graph.add_node("structured", _structured)
        graph.add_node("respond", _respond)
        graph.set_entry_point("navigate")
        graph.add_edge("navigate", "semantic")
        graph.add_edge("semantic", "structured")
        graph.add_edge("structured", "respond")
        graph.add_edge("respond", END)
        return graph.compile()

    def run(self, question: str, document_name: str) -> QueryResponse:
        if not self._graph:
            return self.answer(question=question, document_name=document_name)
        state = self._graph.invoke({"question": question, "document_name": document_name, "tool_trace": []})
        return state["response"]
