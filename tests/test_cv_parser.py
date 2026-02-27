"""Tests for immermatch.cv_parser — text extraction and cleaning."""

from pathlib import Path

import pytest

from immermatch.cv_parser import _clean_text, extract_text


class TestCleanText:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  hello  ", "hello"),
            ("a\n\n\nb", "a\n\nb"),
            ("a\n\n\n\nb", "a\n\nb"),
            ("  line one  \n  line two  ", "line one\nline two"),
        ],
    )
    def test_clean_text_normalization(self, raw: str, expected: str):
        assert _clean_text(raw) == expected


class TestExtractText:
    def test_txt_file(self, fixtures_dir: Path):
        text = extract_text(fixtures_dir / "sample.txt")
        assert "John Doe" in text
        assert "Python" in text

    def test_md_file(self, fixtures_dir: Path):
        text = extract_text(fixtures_dir / "sample.md")
        assert "John Doe" in text
        assert "Software Engineer" in text

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            extract_text(tmp_path / "nonexistent.txt")

    def test_unsupported_extension(self, tmp_path: Path):
        p = tmp_path / "photo.jpg"
        p.write_text("not a cv")
        with pytest.raises(ValueError, match="Unsupported file format"):
            extract_text(p)

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.txt"
        p.write_text("")
        with pytest.raises(ValueError, match="No text could be extracted"):
            extract_text(p)
