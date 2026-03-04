from src.agents.extractor import ExtractionRouter
from src.agents.triage import DomainClassifier, TriageAgent
from src.models.extraction import ExtractedDocument
from src.models.profile import CostEstimate, DocumentProfile, DomainHint, LayoutComplexity, OriginType
from src.strategies.fast_text import FastTextExtractor


def test_triage_detect_origin_scanned():
    agent = TriageAgent()
    metrics = {"avg_char_density": 0.0005, "image_ratio": 0.8}
    assert agent._detect_origin(metrics) == OriginType.SCANNED_IMAGE


def test_triage_detect_origin_digital():
    agent = TriageAgent()
    metrics = {"avg_char_density": 0.05, "image_ratio": 0.1}
    assert agent._detect_origin(metrics) == OriginType.NATIVE_DIGITAL


def test_triage_detect_origin_form_fillable():
    agent = TriageAgent()
    metrics = {"avg_char_density": 0.0025, "image_ratio": 0.05, "widget_page_ratio": 0.4}
    assert agent._detect_origin(metrics) == OriginType.FORM_FILLABLE


def test_triage_layout_complexity_detection():
    agent = TriageAgent()
    assert agent._detect_layout({"table_page_ratio": 0.4, "multi_column_ratio": 0.0, "figure_page_ratio": 0.0, "avg_column_count": 1.0}) == LayoutComplexity.TABLE_HEAVY
    assert agent._detect_layout({"table_page_ratio": 0.0, "multi_column_ratio": 0.3, "figure_page_ratio": 0.0, "avg_column_count": 2.0}) == LayoutComplexity.MULTI_COLUMN
    assert agent._detect_layout({"table_page_ratio": 0.2, "multi_column_ratio": 0.3, "figure_page_ratio": 0.0, "avg_column_count": 2.0}) == LayoutComplexity.MIXED


def test_triage_domain_hint_keyword_strategy():
    agent = TriageAgent()
    assert agent._detect_domain({"text_sample": "tax revenue fiscal year"}) == DomainHint.FINANCIAL
    assert agent._detect_domain({"text_sample": "plaintiff appeals the court"}) == DomainHint.LEGAL
    assert agent._detect_domain({"text_sample": "api protocol architecture"}) == DomainHint.TECHNICAL


class _AlwaysMedicalClassifier(DomainClassifier):
    def classify(self, text: str) -> DomainHint:
        return DomainHint.MEDICAL


def test_triage_domain_classifier_is_pluggable():
    agent = TriageAgent(domain_classifier=_AlwaysMedicalClassifier())
    assert agent._detect_domain({"text_sample": "any text"}) == DomainHint.MEDICAL


def test_triage_domain_keywords_loaded_from_config(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "domain_keywords:\n"
        "  technical:\n"
        "    - semiconductor\n",
        encoding="utf-8",
    )
    agent = TriageAgent(rules_path=str(rules_path))
    assert agent._detect_domain({"text_sample": "advanced semiconductor process node"}) == DomainHint.TECHNICAL
    # Existing defaults remain available after deep merge.
    assert agent._detect_domain({"text_sample": "tax revenue fiscal quarter"}) == DomainHint.FINANCIAL


def test_triage_custom_domain_onboarded_from_config(tmp_path):
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "domain_keywords:\n"
        "  procurement:\n"
        "    - tender\n",
        encoding="utf-8",
    )
    agent = TriageAgent(rules_path=str(rules_path))
    hint, label = agent._detect_domain_with_label({"text_sample": "open tender and procurement policy"})
    assert hint == DomainHint.CUSTOM
    assert label == "procurement"


def test_profile_document_known_scanned_type(monkeypatch, tmp_path):
    agent = TriageAgent()
    doc_path = tmp_path / "dummy.pdf"
    doc_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        agent,
        "_gather_metrics",
        lambda _: {
            "total_pages": 95,
            "avg_chars_per_page": 8,
            "avg_char_density": 0.00002,
            "image_ratio": 0.92,
            "table_page_ratio": 0.0,
            "multi_column_ratio": 0.0,
            "avg_column_count": 1.0,
            "figure_page_ratio": 0.0,
            "font_metadata_ratio": 0.0,
            "widget_page_ratio": 0.0,
            "text_sample": "auditor report financial statement",
            "amharic_char_ratio": 0.0,
        },
    )

    profile = agent.profile_document(str(doc_path), "class_b")
    assert profile.origin_type == OriginType.SCANNED_IMAGE
    assert profile.layout_complexity == LayoutComplexity.SINGLE_COLUMN
    assert profile.domain_hint == DomainHint.FINANCIAL
    assert profile.estimated_extraction_cost == CostEstimate.NEEDS_VISION_MODEL


def test_profile_document_known_table_heavy_type(monkeypatch, tmp_path):
    agent = TriageAgent()
    doc_path = tmp_path / "dummy.pdf"
    doc_path.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(
        agent,
        "_gather_metrics",
        lambda _: {
            "total_pages": 60,
            "avg_chars_per_page": 1800,
            "avg_char_density": 0.0039,
            "image_ratio": 0.01,
            "table_page_ratio": 0.45,
            "multi_column_ratio": 0.35,
            "avg_column_count": 2.0,
            "figure_page_ratio": 0.0,
            "font_metadata_ratio": 1.0,
            "widget_page_ratio": 0.0,
            "text_sample": "tax expenditure fiscal import duty",
            "amharic_char_ratio": 0.0,
        },
    )

    profile = agent.profile_document(str(doc_path), "class_d")
    assert profile.origin_type == OriginType.NATIVE_DIGITAL
    assert profile.layout_complexity == LayoutComplexity.MIXED
    assert profile.domain_hint == DomainHint.FINANCIAL
    assert profile.estimated_extraction_cost == CostEstimate.NEEDS_LAYOUT_MODEL


def test_extraction_router_escalation(tmp_path, monkeypatch):
    ledger = tmp_path / "test_ledger.jsonl"
    router = ExtractionRouter(ledger_path=str(ledger))

    profile = DocumentProfile(
        document_id="test_doc",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=CostEstimate.FAST_TEXT_SUFFICIENT,
        page_count=5,
    )

    dummy_doc = ExtractedDocument(document_id="test_doc", total_processing_time=0.1)

    monkeypatch.setattr(router.strategies["strategy_a"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_a"], "get_confidence", lambda: 0.50)
    monkeypatch.setattr(router.strategies["strategy_a"], "get_cost_estimate", lambda: 0.00)
    monkeypatch.setattr(router.strategies["strategy_b"], "extract", lambda _f, _p: dummy_doc)
    monkeypatch.setattr(router.strategies["strategy_b"], "get_confidence", lambda: 0.91)
    monkeypatch.setattr(router.strategies["strategy_b"], "get_cost_estimate", lambda: 0.01)

    router.execute_extraction("dummy.pdf", profile, threshold=0.80)

    with open(str(ledger), "r", encoding="utf-8") as file_handle:
        log = file_handle.read()
        assert "Strategy A -> Escalated to B" in log


class _FakePage:
    def __init__(self, text: str, width: float, height: float, image_area: float):
        self._text = text
        self.width = width
        self.height = height
        self.images = [{"width": image_area, "height": 1}] if image_area > 0 else []

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return []


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _doc_profile() -> DocumentProfile:
    return DocumentProfile(
        document_id="doc",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=CostEstimate.FAST_TEXT_SUFFICIENT,
        page_count=1,
    )


def test_fast_text_confidence_low_signal(monkeypatch):
    fake_pdf = _FakePdf([_FakePage(text="short", width=1000, height=1000, image_area=700000)])
    monkeypatch.setattr("src.strategies.fast_text.pdfplumber.open", lambda _path: fake_pdf)

    extractor = FastTextExtractor()
    extractor.extract("dummy.pdf", _doc_profile())
    assert extractor.get_confidence() < 0.50


def test_fast_text_confidence_high_signal(monkeypatch):
    rich_text = " ".join(["revenue"] * 200)
    fake_pdf = _FakePdf([_FakePage(text=rich_text, width=1000, height=1000, image_area=0)])
    monkeypatch.setattr("src.strategies.fast_text.pdfplumber.open", lambda _path: fake_pdf)

    extractor = FastTextExtractor()
    extractor.extract("dummy.pdf", _doc_profile())
    assert extractor.get_confidence() > 0.80
