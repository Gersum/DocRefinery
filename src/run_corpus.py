import argparse
from pathlib import Path
from typing import Dict

from src.agents.extractor import ExtractionRouter
from src.agents.triage import TriageAgent


INTERIM_DOC_PLAN: Dict[str, str] = {
    # Class A (Annual Financial Report - native digital)
    "CBE_Annual_Report_Part_1": "CBE ANNUAL REPORT 2023-24.pdf",
    "CBE_Annual_Report_Part_2": "CBE Annual Report 2018-19.pdf",
    "CBE_Annual_Report_Part_3": "Annual_Report_JUNE-2023.pdf",
    # Class B (Scanned Government/Legal)
    "DBE_Audit_Report_Part_1": "Audit Report - 2023.pdf",
    "DBE_Audit_Report_Part_2": "2018_Audited_Financial_Statement_Report.pdf",
    "DBE_Audit_Report_Part_3": "2019_Audited_Financial_Statement_Report.pdf",
    # Class C (Technical Assessment Report - mixed)
    "FTA_Performance_Survey_Part_1": "fta_performance_survey_final_report_2022.pdf",
    "FTA_Performance_Survey_Part_2": "Security_Vulnerability_Disclosure_Standard_Procedure_1.pdf",
    "FTA_Performance_Survey_Part_3": "20191010_Pharmaceutical-Manufacturing-Opportunites-in-Ethiopia_VF.pdf",
    # Class D (Structured Data Report - table heavy)
    "Tax_Expenditure_Ethiopia_Part_1": "tax_expenditure_ethiopia_2021_22.pdf",
    "Tax_Expenditure_Ethiopia_Part_2": "Consumer Price Index July 2025.pdf",
    "Tax_Expenditure_Ethiopia_Part_3": "Consumer Price Index August 2025.pdf",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate interim profiles and extraction ledger.")
    parser.add_argument("--corpus-dir", default="corpus", help="Directory containing PDF corpus.")
    parser.add_argument("--rules-path", default="rubric/extraction_rules.yaml", help="Extraction configuration YAML.")
    parser.add_argument("--clean", action="store_true", help="Clean existing profile and extraction artifacts first.")
    return parser.parse_args()


def ensure_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required corpus file not found: {path}")


def clean_artifacts(profiles_dir: Path, extractions_dir: Path, ledger_path: Path, review_queue_path: Path) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    extractions_dir.mkdir(parents=True, exist_ok=True)
    for target_dir in [profiles_dir, extractions_dir]:
        for item in target_dir.glob("*.json"):
            item.unlink()
    if ledger_path.exists():
        ledger_path.unlink()
    if review_queue_path.exists():
        review_queue_path.unlink()


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    corpus_dir = (root / args.corpus_dir).resolve()
    profiles_dir = root / ".refinery" / "profiles"
    extractions_dir = root / ".refinery" / "extractions"
    ledger_path = root / ".refinery" / "extraction_ledger.jsonl"
    review_queue_path = root / ".refinery" / "review_queue.jsonl"

    if args.clean:
        clean_artifacts(profiles_dir, extractions_dir, ledger_path, review_queue_path)
    else:
        profiles_dir.mkdir(parents=True, exist_ok=True)
        extractions_dir.mkdir(parents=True, exist_ok=True)

    triage = TriageAgent(sample_pages=5, rules_path=args.rules_path)
    router = ExtractionRouter(ledger_path=str(ledger_path), rules_path=args.rules_path)

    processed = 0
    for profile_id, filename in INTERIM_DOC_PLAN.items():
        pdf_path = corpus_dir / filename
        ensure_file_exists(pdf_path)

        print(f"Processing {profile_id} from {filename} ...")
        profile = triage.profile_document(str(pdf_path), profile_id)
        extracted = router.execute_extraction(str(pdf_path), profile)

        (profiles_dir / f"{profile_id}.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        (extractions_dir / f"{profile_id}.json").write_text(extracted.model_dump_json(indent=2), encoding="utf-8")
        processed += 1

    print(f"Completed artifact generation for {processed} documents.")


if __name__ == "__main__":
    main()
