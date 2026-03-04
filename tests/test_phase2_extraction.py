import json
from types import SimpleNamespace

from src.agents.extractor import ExtractionRouter
from src.models.extraction import ExtractedDocument, ExtractedPage, ExtractedText
from src.models.profile import CostEstimate, DocumentProfile, DomainHint, LayoutComplexity, OriginType
from src.strategies.layout import LayoutExtractor
from src.strategies.vision import VisionExtractor


class _FakeRect:
    def __init__(self, x0: float, y0: float, x1: float, y1: float):
        self.r_x0 = x0
        self.r_y0 = y0
        self.r_x1 = x1
        self.r_y1 = y0
        self.r_x2 = x1
        self.r_y2 = y1
        self.r_x3 = x0
        self.r_y3 = y1


class _FakeCell:
    def __init__(self, text: str, rect: _FakeRect, font_name: str = "Times"):
        self.text = text
        self.rect = rect
        self.font_name = font_name


class _FakeBitmap:
    def __init__(self, rect: _FakeRect):
        self.rect = rect


class _FakeDoclingPage:
    def __init__(self):
        self.word_cells = [
            _FakeCell("Revenue", _FakeRect(10, 700, 70, 715)),
            _FakeCell("$4.2B", _FakeRect(75, 700, 120, 715)),
        ]
        self.textline_cells = []
        self.bitmap_resources = [_FakeBitmap(_FakeRect(100, 400, 300, 520))]


class _FakeDoclingDocument:
    def get_page(self, page_number: int):
        return _FakeDoclingPage()

    def unload(self):
        return None


class _FakeDoclingParser:
    def __init__(self, loglevel: str = "error"):
        self.loglevel = loglevel

    def load(self, file_path: str, lazy: bool = True):
        return _FakeDoclingDocument()


class _FakePdfPage:
    def __init__(self):
        self.width = 600.0
        self.height = 800.0
        self.images = [{"width": 100, "height": 100}]
        self.chars = [{"fontname": "Times"}]

    def find_tables(self):
        return []

    def extract_tables(self):
        return [[["Year", "Revenue"], ["2024", "$4.2B"]]]

    def extract_text(self):
        return "Revenue $4.2B"


class _FakePdf:
    def __init__(self):
        self.pages = [_FakePdfPage()]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _profile(cost: CostEstimate) -> DocumentProfile:
    return DocumentProfile(
        document_id="doc",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.MULTI_COLUMN,
        domain_hint=DomainHint.FINANCIAL,
        estimated_extraction_cost=cost,
        page_count=1,
    )


def test_layout_extractor_docling_adapter(monkeypatch):
    monkeypatch.setattr("src.strategies.layout.pdfplumber.open", lambda _path: _FakePdf())
    extractor = LayoutExtractor()
    extractor.docling_parser_cls = _FakeDoclingParser

    result = extractor.extract("dummy.pdf", _profile(CostEstimate.NEEDS_LAYOUT_MODEL))
    assert result.pages
    page = result.pages[0]
    assert page.strategy_used == "Strategy B - LayoutExtractor"
    assert len(page.text_blocks) >= 2
    assert page.text_blocks[0].text in {"Revenue", "$4.2B"}
    assert len(page.tables) == 1
    assert len(page.figures) == 1
    assert extractor.get_confidence() > 0.4


def test_vision_budget_guard_stops_over_budget(monkeypatch):
    class _FakeImage:
        def save(self, buffer, format="PNG"):
            buffer.write(b"png")

    class _FakeVisionPage(_FakePdfPage):
        def to_image(self, resolution=120):
            return SimpleNamespace(original=_FakeImage())

    class _FakeVisionPdf:
        def __init__(self):
            self.pages = [_FakeVisionPage(), _FakeVisionPage(), _FakeVisionPage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    call_count = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "usage": {"total_tokens": 10000},
                "choices": [{"message": {"content": "{\"text_blocks\": [{\"text\": \"OCR\", \"bbox\": [0,0,10,10]}], \"tables\": []}"}}],
            }

    def _fake_post(*args, **kwargs):
        call_count["n"] += 1
        return _Resp()

    monkeypatch.setattr("src.strategies.vision.pdfplumber.open", lambda _path: _FakeVisionPdf())
    monkeypatch.setattr("src.strategies.vision.requests.post", _fake_post)

    extractor = VisionExtractor(max_budget=0.01)
    extractor.api_key = "test-key"
    result = extractor.extract("dummy.pdf", _profile(CostEstimate.NEEDS_VISION_MODEL))

    assert result.total_cost <= 0.02
    assert call_count["n"] == 1
    assert extractor.get_token_spend() == 10000


def test_router_logs_strategy_trace_and_token_spend(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    router = ExtractionRouter(ledger_path=str(ledger))
    profile = _profile(CostEstimate.NEEDS_VISION_MODEL)

    dummy_page = ExtractedPage(page_num=1, text_blocks=[ExtractedText(text="x", page_num=1)])
    dummy_doc = ExtractedDocument(document_id="doc", pages=[dummy_page], total_processing_time=0.1, total_cost=0.04)

    monkeypatch.setattr(router.strategies["strategy_c"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_confidence", lambda: 0.9)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_cost_estimate", lambda: 0.04)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_token_spend", lambda: 321)

    router.execute_extraction("dummy.pdf", profile, threshold=0.8)

    with open(ledger, "r", encoding="utf-8") as handle:
        record = json.loads(handle.readline())

    assert record["strategy_used"] == "STRATEGY_C"
    assert record["strategy_trace"] == ["strategy_c"]
    assert record["token_spend"] == 321


def test_router_uses_configured_strategy_gates(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "extraction_thresholds:\n"
        "  strategy_a_confidence_gate: 0.90\n"
        "  strategy_b_confidence_gate: 0.80\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    router = ExtractionRouter(ledger_path=str(ledger), rules_path=str(rules))
    profile = _profile(CostEstimate.FAST_TEXT_SUFFICIENT)
    dummy_doc = ExtractedDocument(document_id="doc", pages=[ExtractedPage(page_num=1)], total_processing_time=0.1, total_cost=0.01)

    monkeypatch.setattr(router.strategies["strategy_a"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_a"], "get_confidence", lambda: 0.85)
    monkeypatch.setattr(router.strategies["strategy_a"], "get_cost_estimate", lambda: 0.0)
    monkeypatch.setattr(router.strategies["strategy_b"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_b"], "get_confidence", lambda: 0.82)
    monkeypatch.setattr(router.strategies["strategy_b"], "get_cost_estimate", lambda: 0.01)
    monkeypatch.setattr(router.strategies["strategy_c"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_confidence", lambda: 0.99)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_cost_estimate", lambda: 0.02)

    router.execute_extraction("dummy.pdf", profile)
    with open(ledger, "r", encoding="utf-8") as handle:
        record = json.loads(handle.readline())

    assert record["strategy_used"] == "Strategy A -> Escalated to B"
    assert record["strategy_trace"] == ["strategy_a", "strategy_b"]
    assert record["review_required"] is False


def test_router_flags_low_confidence_outcomes_for_review(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "extraction_thresholds:\n"
        "  strategy_c_review_floor: 0.95\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    router = ExtractionRouter(ledger_path=str(ledger), rules_path=str(rules))
    profile = _profile(CostEstimate.NEEDS_VISION_MODEL)
    dummy_doc = ExtractedDocument(document_id="doc", pages=[ExtractedPage(page_num=1)], total_processing_time=0.1, total_cost=0.02)

    monkeypatch.setattr(router.strategies["strategy_c"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_confidence", lambda: 0.60)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_cost_estimate", lambda: 0.02)
    monkeypatch.setattr(router.strategies["strategy_c"], "get_token_spend", lambda: 123)

    router.execute_extraction("dummy.pdf", profile)

    with open(ledger, "r", encoding="utf-8") as handle:
        record = json.loads(handle.readline())
    with open(tmp_path / "review_queue.jsonl", "r", encoding="utf-8") as handle:
        review_record = json.loads(handle.readline())

    assert record["review_required"] is True
    assert "strategy_c confidence" in record["review_reason"]
    assert record["strategy_used"] == "STRATEGY_C_LOW_CONFIDENCE"
    assert review_record["document_id"] == "doc"
