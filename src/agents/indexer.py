from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List

import requests

from src.agents.vector_store import VectorStore
from src.config import retrieval_preference
from src.models.indexing import PageIndex, PageIndexNode
from src.models.ldu import LDU


class PageIndexBuilder:
    """Builds a recursive PageIndex tree and generates section summaries."""

    def __init__(self, rules_path: str | None = None):
        self.summary_max_chars = int(retrieval_preference("summary_max_chars", 260, rules_path))
        self.summary_model = str(retrieval_preference("summary_model", "openrouter/auto", rules_path))
        self.summary_timeout = int(retrieval_preference("summary_request_timeout_sec", 30, rules_path))
        self.summary_temperature = float(retrieval_preference("summary_temperature", 0.0, rules_path))
        self.summary_max_tokens = int(retrieval_preference("summary_max_tokens", 80, rules_path))
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def _heuristic_summary(self, text: str) -> str:
        compact = " ".join(text.split())
        if len(compact) <= self.summary_max_chars:
            return compact
        return compact[: self.summary_max_chars - 3].rstrip() + "..."

    def _llm_summary(self, text: str) -> str:
        if not self.api_key:
            return self._heuristic_summary(text)
        payload = {
            "model": self.summary_model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Summarize this document section in one concise sentence for index navigation.\n\n"
                        + text[:3000]
                    ),
                }
            ],
            "temperature": self.summary_temperature,
            "max_tokens": self.summary_max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = requests.post(self.api_url, headers=headers, json=payload, timeout=self.summary_timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return self._heuristic_summary(content or text)
        except Exception:
            return self._heuristic_summary(text)

    def _extract_entities(self, text: str) -> list[str]:
        tokens = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text)
        deduped = []
        seen = set()
        for token in tokens:
            if token not in seen:
                deduped.append(token)
                seen.add(token)
        return deduped[:8]

    def build(self, document_id: str, ldus: Iterable[LDU]) -> PageIndex:
        sections: dict[str, dict[str, object]] = {}
        for ldu in ldus:
            section = ldu.parent_section or "Document"
            bucket = sections.setdefault(section, {"texts": [], "pages": []})
            bucket["texts"].append(ldu.content)
            bucket["pages"].extend(ldu.page_refs)

        child_nodes: List[PageIndexNode] = []
        for section_title, payload in sorted(sections.items(), key=lambda kv: min(kv[1]["pages"] or [1])):
            pages = sorted(set(payload["pages"] or [1]))
            joined = "\n".join(payload["texts"])
            summary = self._llm_summary(joined)
            child_nodes.append(
                PageIndexNode(
                    section_title=section_title,
                    page_start=pages[0],
                    page_end=pages[-1],
                    summary=summary,
                    key_entities=self._extract_entities(joined),
                    data_types_present=[],
                    child_sections=[],
                )
            )

        if not child_nodes:
            root = PageIndexNode(section_title="Document Root", page_start=1, page_end=1, summary="Empty index.")
            return PageIndex(document_id=document_id, root_node=root)

        root = PageIndexNode(
            section_title="Document Root",
            page_start=min(node.page_start for node in child_nodes),
            page_end=max(node.page_end for node in child_nodes),
            summary="Hierarchical section index for guided retrieval.",
            child_sections=child_nodes,
        )
        return PageIndex(document_id=document_id, root_node=root)


class PageIndexNavigator:
    """Traverses PageIndex to surface top relevant sections before semantic search."""

    def __init__(self, page_index: PageIndex):
        self.page_index = page_index

    def _score(self, topic_tokens: set[str], node: PageIndexNode) -> float:
        hay = " ".join([node.section_title, node.summary] + node.key_entities).lower()
        node_tokens = set(re.findall(r"[a-z0-9]+", hay))
        if not topic_tokens or not node_tokens:
            return 0.0
        overlap = len(topic_tokens.intersection(node_tokens))
        return overlap / max(1, len(topic_tokens))

    def query(self, topic: str, top_k: int = 3) -> list[PageIndexNode]:
        topic_tokens = set(re.findall(r"[a-z0-9]+", topic.lower()))
        candidates = list(self.page_index.root_node.child_sections)
        candidates.sort(key=lambda node: self._score(topic_tokens, node), reverse=True)
        return candidates[:top_k]


@dataclass
class PrecisionReport:
    naive_precision_at_k: float
    indexed_precision_at_k: float
    naive_hits: int
    indexed_hits: int
    top_sections: list[str]


class RetrievalBenchmark:
    """Compares naive semantic retrieval vs PageIndex-navigated semantic retrieval."""

    @staticmethod
    def _precision(results: list[str], relevant: set[str]) -> tuple[float, int]:
        if not results:
            return 0.0, 0
        hits = sum(1 for item in results if item in relevant)
        return hits / len(results), hits

    def evaluate(
        self,
        topic: str,
        relevant_sections: set[str],
        navigator: PageIndexNavigator,
        vector_store: VectorStore,
        top_k_sections: int = 3,
        top_k_vectors: int = 5,
    ) -> PrecisionReport:
        naive = vector_store.search(topic, top_k=top_k_vectors)
        naive_sections = [hit.parent_section or "" for hit in naive]
        naive_precision, naive_hits = self._precision(naive_sections, relevant_sections)

        scoped_nodes = navigator.query(topic, top_k=top_k_sections)
        scoped_titles = [node.section_title for node in scoped_nodes]
        scoped = vector_store.search(topic, top_k=top_k_vectors, allowed_sections=set(scoped_titles))
        scoped_sections = [hit.parent_section or "" for hit in scoped]
        indexed_precision, indexed_hits = self._precision(scoped_sections, relevant_sections)

        return PrecisionReport(
            naive_precision_at_k=naive_precision,
            indexed_precision_at_k=indexed_precision,
            naive_hits=naive_hits,
            indexed_hits=indexed_hits,
            top_sections=scoped_titles,
        )
