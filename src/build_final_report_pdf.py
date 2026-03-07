from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD = ROOT / "FINAL_REPORT.md"
OUTPUT_PDF = ROOT / "FINAL_REPORT.pdf"


def markdown_to_story(markdown_text: str):
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], spaceAfter=10)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceAfter=8)
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["BodyText"], leading=14, spaceAfter=6)
    bullet = ParagraphStyle("Bullet", parent=styles["BodyText"], leftIndent=14, bulletIndent=6, leading=14, spaceAfter=4)
    code_style = ParagraphStyle("Code", parent=styles["Code"], leading=11)

    story = []
    in_code_block = False
    code_buffer = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            if in_code_block:
                story.append(Preformatted("\n".join(code_buffer), code_style))
                story.append(Spacer(1, 6))
                code_buffer = []
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_buffer.append(line)
            continue

        if not line.strip():
            story.append(Spacer(1, 6))
            continue

        if line.startswith("# "):
            story.append(Paragraph(line[2:].strip(), h1))
            continue
        if line.startswith("## "):
            story.append(Paragraph(line[3:].strip(), h2))
            continue
        if line.startswith("### "):
            story.append(Paragraph(line[4:].strip(), h3))
            continue

        if line.startswith("- "):
            story.append(Paragraph(line[2:].strip(), bullet, bulletText="•"))
            continue

        story.append(Paragraph(line, body))

    if code_buffer:
        story.append(Preformatted("\n".join(code_buffer), code_style))

    return story


def main() -> None:
    if not SOURCE_MD.exists():
        raise FileNotFoundError(f"Missing source report: {SOURCE_MD}")

    md_text = SOURCE_MD.read_text(encoding="utf-8")
    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
        title="Document Intelligence Refinery Final Report",
    )
    story = markdown_to_story(md_text)
    doc.build(story)
    print(f"Wrote {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
