"""CV Parser module - Extracts text from CV files (PDF, DOCX, MD, TXT)."""

import pdfplumber
import docx
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


def extract_text(cv_path: str | Path) -> str:
    """
    Extract text from a CV file. Supports PDF, DOCX, Markdown, and plain text.

    Args:
        cv_path: Path to the CV file.

    Returns:
        Extracted text content as a string.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the format is unsupported or no text could be extracted.
    """
    cv_path = Path(cv_path)

    if not cv_path.exists():
        raise FileNotFoundError(f"CV file not found: {cv_path}")

    suffix = cv_path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format: {suffix}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if suffix == ".pdf":
        text = _extract_from_pdf(cv_path)
    elif suffix == ".docx":
        text = _extract_from_docx(cv_path)
    else:  # .md, .txt
        text = cv_path.read_text(encoding="utf-8")

    text = _clean_text(text)

    if not text:
        raise ValueError(f"No text could be extracted from: {cv_path}")

    return text


def _extract_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF file."""
    text_parts: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    return "\n\n".join(text_parts)


def _extract_from_docx(docx_path: Path) -> str:
    """Extract text from a DOCX file."""
    doc = docx.Document(str(docx_path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _clean_text(text: str) -> str:
    """Clean up whitespace while preserving structure."""
    lines = text.split("\n")
    cleaned_lines = [line.strip() for line in lines]
    cleaned_text = "\n".join(cleaned_lines)

    while "\n\n\n" in cleaned_text:
        cleaned_text = cleaned_text.replace("\n\n\n", "\n\n")

    return cleaned_text.strip()


