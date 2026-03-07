from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

from src.config import retrieval_preference
from src.models.ldu import LDU

try:
    import chromadb  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    chromadb = None


@dataclass
class VectorSearchResult:
    ldu_id: str
    document_id: str
    content: str
    score: float
    chunk_type: str
    parent_section: str | None
    page_refs: list[int]
    content_hash: str
    bbox: dict | None


class VectorStore(Protocol):
    def ingest_ldus(self, ldus: Sequence[LDU]) -> None:
        ...

    def search(self, query: str, top_k: int = 5, allowed_sections: set[str] | None = None) -> list[VectorSearchResult]:
        ...


class LocalVectorStore:
    """
    Local vector store for LDUs.
    Uses deterministic hashed embeddings so it stays offline and reproducible.
    """

    def __init__(self, rules_path: str | None = None):
        self.embedding_dim = int(retrieval_preference("embedding_dimension", 256, rules_path))
        self.min_score = float(retrieval_preference("similarity_min_score", 0.05, rules_path))
        self._records: list[LDU] = []
        self._vectors: list[list[float]] = []

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.embedding_dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.embedding_dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def ingest_ldus(self, ldus: Sequence[LDU]) -> None:
        for ldu in ldus:
            self._records.append(ldu)
            self._vectors.append(self._embed(ldu.content))

    def _cosine(self, v1: Iterable[float], v2: Iterable[float]) -> float:
        return sum(a * b for a, b in zip(v1, v2))

    def search(self, query: str, top_k: int = 5, allowed_sections: set[str] | None = None) -> list[VectorSearchResult]:
        qv = self._embed(query)
        scored: list[VectorSearchResult] = []
        for record, vec in zip(self._records, self._vectors):
            if allowed_sections and (record.parent_section or "") not in allowed_sections:
                continue
            score = self._cosine(qv, vec)
            if score < self.min_score:
                continue
            scored.append(
                VectorSearchResult(
                    ldu_id=record.ldu_id,
                    document_id=record.document_id,
                    content=record.content,
                    score=score,
                    chunk_type=record.chunk_type.value,
                    parent_section=record.parent_section,
                    page_refs=record.page_refs,
                    content_hash=record.content_hash,
                    bbox=record.bounding_box.model_dump() if record.bounding_box else None,
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]


class ChromaVectorStore:
    """
    ChromaDB-backed vector store for local retrieval.
    Falls back to deterministic hashed embeddings for fully offline ingestion.
    """

    def __init__(self, rules_path: str | None = None):
        if chromadb is None:
            raise RuntimeError("chroma backend requested but chromadb is not installed")
        self.embedding_dim = int(retrieval_preference("embedding_dimension", 256, rules_path))
        self.min_score = float(retrieval_preference("similarity_min_score", 0.05, rules_path))
        self.db_path = str(retrieval_preference("vector_chroma_path", ".refinery/chroma", rules_path))
        self.collection_name = str(retrieval_preference("vector_chroma_collection", "ldus", rules_path))
        self.client = chromadb.PersistentClient(path=self.db_path)
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        self._records: dict[str, LDU] = {}

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.embedding_dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.embedding_dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def ingest_ldus(self, ldus: Sequence[LDU]) -> None:
        if not ldus:
            return
        ids = [ldu.ldu_id for ldu in ldus]
        embeddings = [self._embed(ldu.content) for ldu in ldus]
        documents = [ldu.content for ldu in ldus]
        metadatas = [
            {
                "document_id": ldu.document_id,
                "chunk_type": ldu.chunk_type.value,
                "parent_section": ldu.parent_section or "",
                "page_refs": ",".join(str(p) for p in ldu.page_refs),
                "content_hash": ldu.content_hash,
                "bbox": (
                    f"{ldu.bounding_box.x0},{ldu.bounding_box.y0},{ldu.bounding_box.x1},{ldu.bounding_box.y1}"
                    if ldu.bounding_box
                    else ""
                ),
            }
            for ldu in ldus
        ]
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        for ldu in ldus:
            self._records[ldu.ldu_id] = ldu

    def search(self, query: str, top_k: int = 5, allowed_sections: set[str] | None = None) -> list[VectorSearchResult]:
        query_embedding = self._embed(query)
        raw = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=max(top_k * 3, top_k),
            include=["metadatas", "documents", "distances"],
        )

        hits: list[VectorSearchResult] = []
        ids = raw.get("ids", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        distances = raw.get("distances", [[]])[0]
        for idx, ldu_id in enumerate(ids):
            metadata = metadatas[idx] or {}
            parent_section = str(metadata.get("parent_section") or "")
            if allowed_sections and parent_section not in allowed_sections:
                continue
            distance = float(distances[idx]) if idx < len(distances) else 1.0
            score = max(0.0, 1.0 - distance)
            if score < self.min_score:
                continue
            bbox_data = None
            bbox_raw = str(metadata.get("bbox") or "")
            if bbox_raw:
                try:
                    x0, y0, x1, y1 = [float(v) for v in bbox_raw.split(",")]
                    bbox_data = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
                except Exception:
                    bbox_data = None
            page_refs_raw = str(metadata.get("page_refs") or "")
            page_refs = [int(v) for v in page_refs_raw.split(",") if v.strip().isdigit()]
            hits.append(
                VectorSearchResult(
                    ldu_id=ldu_id,
                    document_id=str(metadata.get("document_id") or ""),
                    content=str(documents[idx] or ""),
                    score=score,
                    chunk_type=str(metadata.get("chunk_type") or ""),
                    parent_section=parent_section or None,
                    page_refs=page_refs or [1],
                    content_hash=str(metadata.get("content_hash") or ""),
                    bbox=bbox_data,
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]


def build_vector_store(rules_path: str | None = None) -> VectorStore:
    backend = str(retrieval_preference("vector_backend", "local_hash", rules_path)).strip().lower()
    if backend == "chroma":
        try:
            return ChromaVectorStore(rules_path=rules_path)
        except Exception:
            # Graceful degradation keeps the pipeline runnable without optional deps.
            return LocalVectorStore(rules_path=rules_path)
    return LocalVectorStore(rules_path=rules_path)
