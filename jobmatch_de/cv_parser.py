"""CV Parser module - Extracts text from PDF CVs and converts to markdown."""

import pdfplumber
from pathlib import Path


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """
    Extract text from a PDF file and return as a clean string.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Extracted text content as a string.

    Raises:
        FileNotFoundError: If the PDF file doesn't exist.
        ValueError: If the PDF contains no extractable text.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"CV file not found: {pdf_path}")

    if not pdf_path.suffix.lower() == ".pdf":
        raise ValueError(f"Expected a PDF file, got: {pdf_path.suffix}")

    text_parts: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    if not text_parts:
        raise ValueError(f"No text could be extracted from: {pdf_path}")

    # Join pages with double newlines for separation
    full_text = "\n\n".join(text_parts)

    # Clean up excessive whitespace while preserving structure
    lines = full_text.split("\n")
    cleaned_lines = [line.strip() for line in lines]
    cleaned_text = "\n".join(cleaned_lines)

    # Remove excessive blank lines (more than 2 consecutive)
    while "\n\n\n" in cleaned_text:
        cleaned_text = cleaned_text.replace("\n\n\n", "\n\n")

    return cleaned_text.strip()


def format_cv_as_markdown(cv_text: str) -> str:
    """
    Format extracted CV text as markdown for better LLM processing.

    Args:
        cv_text: Raw extracted text from PDF.

    Returns:
        Markdown-formatted CV text.
    """
    # Wrap in markdown code block for clarity
    return f"""# Candidate CV

```
{cv_text}
```
"""
