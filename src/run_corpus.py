import os
import json
import glob
from src.agents.triage import TriageAgent
from src.agents.extractor import ExtractionRouter

def main():
    target_dir = "/Users/gersumasfaw/Downloads/week3/corpus/"
    triage = TriageAgent(sample_pages=3)
    router = ExtractionRouter(ledger_path=".refinery/extraction_ledger.jsonl")

    target_files = [
        "CBE ANNUAL REPORT 2023-24.pdf",
        "Audit Report - 2023.pdf",
        "fta_performance_survey_final_report_2022.pdf"
    ]
    
    pdfs = [os.path.join(target_dir, f) for f in target_files if os.path.exists(os.path.join(target_dir, f))]
    
    if not pdfs:
        print(f"None of the 3 specified PDF files were found in {target_dir}.")
        return

    # To be extremely rigid about only processing 3
    for pdf_path in pdfs[:3]:
        doc_id = os.path.basename(pdf_path).replace(".pdf", "")
        print(f"Processing {doc_id}...")
        
        profile = triage.profile_document(pdf_path, doc_id)
        os.makedirs(".refinery/profiles", exist_ok=True)
        with open(f".refinery/profiles/{doc_id}.json", "w") as f:
            f.write(profile.model_dump_json(indent=2))
        
        router.execute_extraction(pdf_path, profile)

def generate_mock_profiles_and_ledger(triage: TriageAgent, router: ExtractionRouter):
    # This remains as a fallback if needed but is no longer called in main()
    pass

if __name__ == "__main__":
    main()
