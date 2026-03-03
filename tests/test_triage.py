import pytest
from src.agents.triage import TriageAgent
from src.models.profile import OriginType, LayoutComplexity, DomainHint, CostEstimate
from src.agents.extractor import ExtractionRouter
from src.models.profile import DocumentProfile

def test_triage_detect_origin_scanned():
    agent = TriageAgent()
    metrics = {"avg_char_density": 0.0005, "image_ratio": 0.8}
    assert agent._detect_origin(metrics) == OriginType.SCANNED_IMAGE

def test_triage_detect_origin_digital():
    agent = TriageAgent()
    metrics = {"avg_char_density": 0.05, "image_ratio": 0.1}
    assert agent._detect_origin(metrics) == OriginType.NATIVE_DIGITAL

def test_triage_domain_hint():
    agent = TriageAgent()
    assert agent._detect_domain({"text_sample": "tax revenue fiscal year"}) == DomainHint.FINANCIAL
    assert agent._detect_domain({"text_sample": "plaintiff appeals the court"}) == DomainHint.LEGAL

def test_extraction_router_escalation(tmp_path, mocker):
    ledger = tmp_path / "test_ledger.jsonl"
    router = ExtractionRouter(ledger_path=str(ledger))
    
    profile = DocumentProfile(
        document_id="test_doc",
        origin_type=OriginType.NATIVE_DIGITAL,
        layout_complexity=LayoutComplexity.SINGLE_COLUMN,
        domain_hint=DomainHint.GENERAL,
        estimated_extraction_cost=CostEstimate.FAST_TEXT_SUFFICIENT,
        page_count=5
    )
    
    from src.models.extraction import ExtractedDocument
    dummy_doc = ExtractedDocument(document_id="test_doc")
    
    mocker.patch.object(router.strategies["strategy_a"], "extract", return_value=dummy_doc)
    mocker.patch.object(router.strategies["strategy_a"], "get_confidence", return_value=0.50)
    
    router.execute_extraction("dummy.pdf", profile, threshold=0.80)
    
    with open(str(ledger), "r") as f:
        log = f.read()
        assert "Strategy A -> Escalated to B" in log
