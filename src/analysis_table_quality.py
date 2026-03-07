from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber


INTERIM_DOC_PLAN = {
    "CBE_Annual_Report_Part_1": "CBE ANNUAL REPORT 2023-24.pdf",
    "CBE_Annual_Report_Part_2": "CBE Annual Report 2018-19.pdf",
    "CBE_Annual_Report_Part_3": "Annual_Report_JUNE-2023.pdf",
    "DBE_Audit_Report_Part_1": "Audit Report - 2023.pdf",
    "DBE_Audit_Report_Part_2": "2018_Audited_Financial_Statement_Report.pdf",
    "DBE_Audit_Report_Part_3": "2019_Audited_Financial_Statement_Report.pdf",
    "FTA_Performance_Survey_Part_1": "fta_performance_survey_final_report_2022.pdf",
    "FTA_Performance_Survey_Part_2": "Security_Vulnerability_Disclosure_Standard_Procedure_1.pdf",
    "FTA_Performance_Survey_Part_3": "20191010_Pharmaceutical-Manufacturing-Opportunites-in-Ethiopia_VF.pdf",
    "Tax_Expenditure_Ethiopia_Part_1": "tax_expenditure_ethiopia_2021_22.pdf",
    "Tax_Expenditure_Ethiopia_Part_2": "Consumer Price Index July 2025.pdf",
    "Tax_Expenditure_Ethiopia_Part_3": "Consumer Price Index August 2025.pdf",
}


def infer_doc_class(profile_id: str) -> str:
    if profile_id.startswith("CBE_Annual_Report"):
        return "class_a"
    if profile_id.startswith("DBE_Audit_Report"):
        return "class_b"
    if profile_id.startswith("FTA_Performance_Survey"):
        return "class_c"
    return "class_d"


def has_pdf_table(page: pdfplumber.page.Page) -> bool:
    try:
        found = page.find_tables() or []
        if found:
            return True
    except Exception:
        pass

    try:
        for table in page.extract_tables() or []:
            rows = [row for row in table if row and any(cell for cell in row)]
            if len(rows) >= 2:
                return True
    except Exception:
        pass

    return False


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def main() -> None:
    root = Path.cwd()
    corpus_dir = root / "corpus"
    extractions_dir = root / ".refinery" / "extractions"
    ledger_path = root / ".refinery" / "extraction_ledger.jsonl"
    out_path = root / ".refinery" / "analysis" / "final_extraction_quality_metrics.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    overall = Counter()
    per_class = defaultdict(Counter)
    per_document: dict[str, dict[str, object]] = {}

    for profile_id, filename in INTERIM_DOC_PLAN.items():
        extraction_file = extractions_dir / f"{profile_id}.json"
        if not extraction_file.exists():
            continue

        extracted = json.loads(extraction_file.read_text(encoding="utf-8"))
        pred_pages = {
            int(page["page_num"]): (len(page.get("tables", [])) > 0)
            for page in extracted.get("pages", [])
        }

        truth_pages: dict[int, bool] = {}
        with pdfplumber.open(str(corpus_dir / filename)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                truth_pages[page_num] = has_pdf_table(page)

        tp = fp = fn = tn = 0
        for page_num, truth in truth_pages.items():
            pred = pred_pages.get(page_num, False)
            if pred and truth:
                tp += 1
            elif pred and not truth:
                fp += 1
            elif (not pred) and truth:
                fn += 1
            else:
                tn += 1

        precision, recall, f1 = precision_recall_f1(tp, fp, fn)
        doc_class = infer_doc_class(profile_id)

        overall.update({"tp": tp, "fp": fp, "fn": fn, "tn": tn, "pages": len(truth_pages)})
        per_class[doc_class].update(
            {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "pages": len(truth_pages), "documents": 1}
        )

        per_document[profile_id] = {
            "document": filename,
            "class": doc_class,
            "pages": len(truth_pages),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    overall_precision, overall_recall, overall_f1 = precision_recall_f1(
        overall["tp"], overall["fp"], overall["fn"]
    )

    class_metrics: dict[str, dict[str, object]] = {}
    for doc_class, counts in per_class.items():
        precision, recall, f1 = precision_recall_f1(counts["tp"], counts["fp"], counts["fn"])
        class_metrics[doc_class] = {
            "documents": counts["documents"],
            "pages": counts["pages"],
            "tp": counts["tp"],
            "fp": counts["fp"],
            "fn": counts["fn"],
            "tn": counts["tn"],
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    ledger_rows = []
    if ledger_path.exists():
        with ledger_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    ledger_rows.append(json.loads(line))

    strategy_distribution = Counter(row.get("strategy_used", "UNKNOWN") for row in ledger_rows)
    review_required_count = sum(1 for row in ledger_rows if row.get("review_required"))
    avg_final_confidence = (
        sum(float(row.get("confidence_score", 0.0)) for row in ledger_rows) / max(1, len(ledger_rows))
    )

    result = {
        "metric_definition": {
            "table_detection_unit": "page-level binary classification",
            "ground_truth_proxy": "pdfplumber page has table if find_tables() or extract_tables() returns >=1 non-trivial table",
            "prediction": "extraction output page has tables list length > 0",
        },
        "overall_table_extraction": {
            "pages": overall["pages"],
            "tp": overall["tp"],
            "fp": overall["fp"],
            "fn": overall["fn"],
            "tn": overall["tn"],
            "precision": round(overall_precision, 4),
            "recall": round(overall_recall, 4),
            "f1": round(overall_f1, 4),
        },
        "class_table_extraction": class_metrics,
        "per_document_table_extraction": per_document,
        "pipeline_quality": {
            "ledger_entries": len(ledger_rows),
            "avg_final_confidence": round(avg_final_confidence, 4),
            "review_required_count": review_required_count,
            "strategy_distribution": dict(strategy_distribution),
        },
    }

    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
