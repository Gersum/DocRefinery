from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Iterable, List

from src.config import retrieval_preference
from src.models.ldu import ChunkType, LDU


@dataclass
class FactRecord:
    document_id: str
    document_name: str
    ldu_id: str
    key: str
    value: str
    unit: str
    page_number: int
    content_hash: str
    bbox_json: str


class FactTableExtractor:
    """Extracts financial/numeric facts from LDUs and stores them in SQLite for structured querying."""

    KEY_VALUE_PATTERN = re.compile(
        r"(?P<key>[A-Za-z][A-Za-z0-9 _/\\-]{2,40})\s*[:=]\s*(?P<value>[$€£]?\s?-?\d[\d,]*(?:\.\d+)?\s*(?:%|B|M|K|million|billion)?)"
    )

    def __init__(self, rules_path: str | None = None):
        self.db_path = str(retrieval_preference("fact_table_db_path", ".refinery/facts.db", rules_path))
        self.min_numeric_length = int(retrieval_preference("fact_min_numeric_length", 1, rules_path))
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            # Best-effort PRAGMA; don't fail if the sqlite build doesn't support it
            pass
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    ldu_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    unit TEXT,
                    page_number INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    bbox_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_doc_key ON facts(document_id, fact_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_page ON facts(document_id, page_number)"
            )

    def _normalize_unit(self, value: str) -> str:
        value = value.strip()
        if value.endswith("%"):
            return "%"
        for suffix in ["B", "M", "K", "million", "billion"]:
            if value.lower().endswith(suffix.lower()):
                return suffix
        if value.startswith("$"):
            return "$"
        return ""

    def _extract_key_value_facts(self, ldu: LDU, document_name: str) -> list[FactRecord]:
        facts: list[FactRecord] = []
        for match in self.KEY_VALUE_PATTERN.finditer(ldu.content):
            key = match.group("key").strip()
            value = match.group("value").strip()
            numeric_chars = re.findall(r"\d", value)
            if len(numeric_chars) < self.min_numeric_length:
                continue
            facts.append(
                FactRecord(
                    document_id=ldu.document_id,
                    document_name=document_name,
                    ldu_id=ldu.ldu_id,
                    key=key,
                    value=value,
                    unit=self._normalize_unit(value),
                    page_number=ldu.page_refs[0] if getattr(ldu, "page_refs", None) else -1,
                    content_hash=ldu.content_hash,
                    bbox_json=(
                        json.dumps(ldu.bounding_box.model_dump())
                        if getattr(ldu, "bounding_box", None) and hasattr(ldu.bounding_box, "model_dump")
                        else "{}"
                    ),
                )
            )
        return facts

    def _extract_table_facts(self, ldu: LDU, document_name: str) -> list[FactRecord]:
        if ldu.chunk_type != ChunkType.TABLE:
            return []
        headers = [str(h).strip() for h in ldu.metadata.get("table_headers", []) if str(h).strip()]
        rows = [row.strip() for row in ldu.content.splitlines() if row.strip()]
        if not headers or not rows:
            return []

        facts: list[FactRecord] = []
        for row in rows:
            cells = [cell.strip() for cell in row.split("|")]
            if len(cells) < 2:
                continue
            row_label = cells[0]
            for idx, cell in enumerate(cells[1:], start=1):
                if not re.search(r"\d", cell):
                    continue
                header = headers[idx] if idx < len(headers) else f"col_{idx}"
                facts.append(
                    FactRecord(
                        document_id=ldu.document_id,
                        document_name=document_name,
                        ldu_id=ldu.ldu_id,
                        key=f"{row_label}::{header}",
                        value=cell,
                        unit=self._normalize_unit(cell),
                        page_number=ldu.page_refs[0] if getattr(ldu, "page_refs", None) else -1,
                        content_hash=ldu.content_hash,
                        bbox_json=(
                            json.dumps(ldu.bounding_box.model_dump())
                            if getattr(ldu, "bounding_box", None) and hasattr(ldu.bounding_box, "model_dump")
                            else "{}"
                        ),
                    )
                )
        return facts

    def ingest_ldus(self, ldus: Iterable[LDU], document_name: str) -> int:
        all_facts: list[FactRecord] = []
        for ldu in ldus:
            all_facts.extend(self._extract_key_value_facts(ldu, document_name))
            all_facts.extend(self._extract_table_facts(ldu, document_name))

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO facts (
                    document_id, document_name, ldu_id, fact_key, fact_value, unit,
                    page_number, content_hash, bbox_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        fact.document_id,
                        fact.document_name,
                        fact.ldu_id,
                        fact.key,
                        fact.value,
                        fact.unit,
                        fact.page_number,
                        fact.content_hash,
                        fact.bbox_json,
                    )
                    for fact in all_facts
                ],
            )
        return len(all_facts)

    def query(self, query_text: str, limit: int = 10) -> list[dict]:
        like = f"%{query_text.strip()}%"
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT document_id, document_name, ldu_id, fact_key, fact_value, unit,
                       page_number, content_hash, bbox_json
                FROM facts
                WHERE fact_key LIKE ? OR fact_value LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (like, like, limit),
            )
            rows = cur.fetchall()

        return [
            {
                "document_id": row[0],
                "document_name": row[1],
                "ldu_id": row[2],
                "key": row[3],
                "value": row[4],
                "unit": row[5],
                "page_number": row[6],
                "content_hash": row[7],
                "bbox": json.loads(row[8] or "{}"),
            }
            for row in rows
        ]
