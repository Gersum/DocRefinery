import base64
import json
import os
import time
from io import BytesIO
from typing import Any, Dict, List, Optional

import pdfplumber
import requests

from src.config import extraction_threshold
from src.models.extraction import (
    BoundingBox,
    ExtractedDocument,
    ExtractedPage,
    ExtractedTable,
    ExtractedText,
)
from src.models.profile import DocumentProfile
from src.strategies.base import BaseExtractionStrategy


class VisionExtractor(BaseExtractionStrategy):
    """Strategy C: high-cost vision extraction with a secure env-driven API and local fallback."""

    def __init__(self, max_budget: Optional[float] = None, rules_path: Optional[str] = None):
        self._last_confidence = 0.0
        self._last_cost = 0.0
        self._last_token_spend = 0
        self._budget_exhausted = False
        self.max_budget = max_budget if max_budget is not None else float(extraction_threshold("vision_budget_cap_usd", 1.00, rules_path))
        self.max_pages = int(extraction_threshold("vision_max_pages_per_document", 8, rules_path))
        self.min_remaining_budget_for_call = float(extraction_threshold("vision_min_remaining_budget_for_call", 0.01, rules_path))
        self.base_confidence = float(extraction_threshold("strategy_c_base_confidence", 0.25, rules_path))
        self.text_confidence = float(extraction_threshold("strategy_c_text_confidence", 0.65, rules_path))
        self.table_confidence = float(extraction_threshold("strategy_c_table_confidence", 0.75, rules_path))
        self.vlm_success_confidence_with_text = float(
            extraction_threshold("strategy_c_vlm_success_confidence_with_text", 0.90, rules_path)
        )
        self.vlm_success_confidence_without_text = float(
            extraction_threshold("strategy_c_vlm_success_confidence_without_text", 0.55, rules_path)
        )
        self.budget_exhausted_confidence_cap = float(
            extraction_threshold("strategy_c_budget_exhausted_confidence_cap", 0.85, rules_path)
        )
        self.render_resolution_dpi = int(extraction_threshold("strategy_c_render_resolution_dpi", 120, rules_path))
        self.token_cost_per_token_usd = float(extraction_threshold("strategy_c_token_cost_per_token_usd", 0.000002, rules_path))
        self.request_timeout_sec = int(extraction_threshold("strategy_c_request_timeout_sec", 60, rules_path))
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model = os.getenv("OPENROUTER_VISION_MODEL", "openrouter/auto")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def _img_to_base64(self, image: Any) -> str:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _estimate_cost(self, total_tokens: int) -> float:
        return float(total_tokens) * self.token_cost_per_token_usd

    def _call_openrouter_vision(self, base64_img: str) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None
        if self._last_cost >= self.max_budget:
            self._budget_exhausted = True
            return None
        if (self.max_budget - self._last_cost) < self.min_remaining_budget_for_call:
            self._budget_exhausted = True
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        prompt = (
            "Extract document content from this page. "
            "Return valid JSON with keys: text_blocks (list of {text,bbox}), "
            "tables (list of {headers,rows,bbox})."
        )
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}},
                    ],
                }
            ],
        }

        response = requests.post(self.api_url, headers=headers, json=payload, timeout=self.request_timeout_sec)
        response.raise_for_status()
        result = response.json()
        usage = result.get("usage", {})
        total_tokens = int(usage.get("total_tokens", 0))
        self._last_token_spend += total_tokens
        self._last_cost += self._estimate_cost(total_tokens)
        if self._last_cost >= self.max_budget:
            self._budget_exhausted = True

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]

        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            return None

    def _build_local_table_fallback(self, page: Any, document_id: str, page_number: int) -> List[ExtractedTable]:
        tables = []
        for table_idx, raw_table in enumerate(page.extract_tables() or [], start=1):
            rows = [row for row in raw_table if row and any(cell for cell in row)]
            if len(rows) < 2:
                continue
            headers = [str(cell or "").strip() for cell in rows[0]]
            data_rows = [[str(cell or "").strip() for cell in row] for row in rows[1:]]
            tables.append(
                ExtractedTable(
                    table_id=f"{document_id}-p{page_number}-t{table_idx}",
                    page_num=page_number,
                    headers=headers,
                    data=data_rows,
                    bbox=BoundingBox(x0=0, y0=0, x1=page.width, y1=page.height),
                )
            )
        return tables

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        pages = []
        self._last_cost = 0.0
        self._last_token_spend = 0
        self._budget_exhausted = False
        confidence_sum = 0.0
        processed_pages = 0

        with pdfplumber.open(file_path) as pdf:
            for page_number, page in enumerate(pdf.pages[: self.max_pages], start=1):
                processed_pages += 1
                text_blocks: List[ExtractedText] = []
                tables: List[ExtractedTable] = self._build_local_table_fallback(page, profile.document_id, page_number)
                page_confidence = self.base_confidence

                baseline_text = page.extract_text() or ""
                if baseline_text.strip():
                    text_blocks.append(
                        ExtractedText(
                            text=baseline_text,
                            page_num=page_number,
                            bbox=BoundingBox(x0=0, y0=0, x1=page.width, y1=page.height),
                        )
                    )
                    page_confidence = self.text_confidence

                if tables:
                    page_confidence = max(page_confidence, self.table_confidence)

                if self.api_key and not self._budget_exhausted:
                    try:
                        image = page.to_image(resolution=self.render_resolution_dpi).original
                        response_data = self._call_openrouter_vision(self._img_to_base64(image))
                    except Exception:
                        response_data = None

                    if response_data:
                        for block in response_data.get("text_blocks", []):
                            text = str(block.get("text", "")).strip()
                            if not text:
                                continue
                            bbox = block.get("bbox", [0, 0, page.width, page.height])
                            if len(bbox) != 4:
                                bbox = [0, 0, page.width, page.height]
                            text_blocks.append(
                                ExtractedText(
                                    text=text,
                                    page_num=page_number,
                                    bbox=BoundingBox(x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3])),
                                )
                            )

                        for table_idx, table in enumerate(response_data.get("tables", []), start=1):
                            headers = [str(cell).strip() for cell in table.get("headers", [])]
                            rows = [[str(cell).strip() for cell in row] for row in table.get("rows", [])]
                            if not headers or not rows:
                                continue
                            bbox = table.get("bbox", [0, 0, page.width, page.height])
                            if len(bbox) != 4:
                                bbox = [0, 0, page.width, page.height]
                            tables.append(
                                ExtractedTable(
                                    table_id=f"{profile.document_id}-p{page_number}-vt{table_idx}",
                                    page_num=page_number,
                                    headers=headers,
                                    data=rows,
                                    bbox=BoundingBox(x0=float(bbox[0]), y0=float(bbox[1]), x1=float(bbox[2]), y1=float(bbox[3])),
                                )
                            )
                        page_confidence = max(
                            page_confidence,
                            self.vlm_success_confidence_with_text if text_blocks else self.vlm_success_confidence_without_text,
                        )

                if self._budget_exhausted:
                    page_confidence = min(page_confidence, self.budget_exhausted_confidence_cap)

                confidence_sum += page_confidence
                pages.append(
                    ExtractedPage(
                        page_num=page_number,
                        text_blocks=text_blocks,
                        tables=tables,
                        figures=[],
                        confidence_score=page_confidence,
                        strategy_used="Strategy C - VisionExtractor",
                    )
                )

        self._last_confidence = confidence_sum / max(1, processed_pages)

        return ExtractedDocument(
            document_id=profile.document_id,
            pages=pages,
            total_processing_time=time.time() - start_time,
            total_cost=self._last_cost,
        )

    def get_confidence(self) -> float:
        return self._last_confidence

    def get_cost_estimate(self) -> float:
        return self._last_cost

    def get_token_spend(self) -> int:
        return self._last_token_spend
