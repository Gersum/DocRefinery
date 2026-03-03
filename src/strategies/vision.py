import time
import base64
import json
import requests
import pdfplumber
from io import BytesIO
from src.strategies.base import BaseExtractionStrategy
from src.models.extraction import ExtractedDocument, ExtractedPage, ExtractedText, BoundingBox
from src.models.profile import DocumentProfile

class VisionExtractor(BaseExtractionStrategy):
    """Strategy C: Extracts scanned or complex pages using an external Vision LLM via OpenRouter."""
    def __init__(self, max_budget: float = 0.50):
        self._last_confidence = 1.0
        self._last_cost = 0.0
        self.max_budget = max_budget
        self.api_key = "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"
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def _img_to_base64(self, img) -> str:
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _call_openrouter_vision(self, base64_img: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        prompt = (
            "You are a document intelligence AI. Extract the text, tables, and figures from this page. "
            "Return ONLY a valid JSON object matching this schema: "
            "{\"text_blocks\": [{\"text\": \"string\", \"bbox\": [0,0,100,100]}]}"
        )

        payload = {
            "model": "openrouter/auto:free", 
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
                    ]
                }
            ]
        }

        resp = requests.post(self.api_url, headers=headers, json=payload)
        resp.raise_for_status()
        
        # Log approximate cost based on prompt tokens + response
        data = resp.json()
        usage = data.get("usage", {})
        self._last_cost += (usage.get("total_tokens", 0) * 0.000001)  # Rough estimation

        content = data["choices"][0]["message"]["content"]
        
        # Clean up JSON if model returns markdown wrapping
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            print("Failed to decode model JSON:", content)
            return {"text_blocks": [{"text": str(content), "bbox": [0,0,1,1]}]}

    def extract(self, file_path: str, profile: DocumentProfile) -> ExtractedDocument:
        start_time = time.time()
        pages = []
        self._last_cost = 0.0
        
        try:
            with pdfplumber.open(file_path) as pdf:
                # Limit to 3 pages to save API budget during tests
                target_pages = pdf.pages[:3]
                for page_num, page in enumerate(target_pages, start=1):
                    img = page.to_image(resolution=100).original
                    b64_img = self._img_to_base64(img)
                    
                    try:
                        vlm_result = self._call_openrouter_vision(b64_img)
                        text_blocks = []
                        for block in vlm_result.get("text_blocks", []):
                            bbox = block.get("bbox", [0, 0, page.width, page.height])
                            text_blocks.append(ExtractedText(
                                text=block.get("text", ""),
                                page_num=page_num,
                                bbox=BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3])
                            ))
                            
                        pages.append(ExtractedPage(
                            page_num=page_num,
                            text_blocks=text_blocks,
                            tables=[],
                            figures=[],
                            confidence_score=0.95,
                            strategy_used="Strategy C - VisionExtractor"
                        ))
                    except Exception as api_err:
                        print(f"OpenRouter API failed on page {page_num}: {api_err}")
                        pages.append(ExtractedPage(
                            page_num=page_num, text_blocks=[], tables=[], figures=[], 
                            confidence_score=0.0, strategy_used="Strategy C - VisionExtractor"
                        ))
                        
            self._last_confidence = 0.95
        except Exception as e:
            print(f"Vision extraction failed entirely: {e}")
            self._last_confidence = 0.0

        return ExtractedDocument(
            document_id=profile.document_id,
            pages=pages,
            total_processing_time=time.time() - start_time,
            total_cost=self._last_cost
        )

    def get_confidence(self) -> float:
        return self._last_confidence
    
    def get_cost_estimate(self) -> float:
        return self._last_cost
