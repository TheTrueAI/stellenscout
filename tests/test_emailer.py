"""Tests for stellenscout.emailer — HTML builder pure functions."""

import pytest

from stellenscout.emailer import _build_html, _build_job_row, _impressum_line


class TestBuildJobRow:
    @pytest.mark.parametrize(
        ("score", "color"),
        [
            (85, "#22c55e"),
            (75, "#eab308"),
            (50, "#f97316"),
        ],
    )
    def test_score_badge_color_thresholds(self, score: int, color: str):
        html = _build_job_row({"title": "Dev", "company": "Co", "score": score, "url": "https://example.com"})
        assert color in html

    def test_contains_title_and_company(self):
        html = _build_job_row({"title": "Engineer", "company": "ACME", "score": 90, "url": "#"})
        assert "Engineer" in html
        assert "ACME" in html


class TestBuildHtml:
    def test_contains_job_count(self):
        jobs = [{"title": "Dev", "company": "Co", "score": 80, "url": "#"}]
        html = _build_html(jobs)
        assert "<strong>1</strong>" in html

    def test_unsubscribe_link_present(self):
        html = _build_html([], unsubscribe_url="https://example.com/unsub")
        assert "https://example.com/unsub" in html

    def test_unsubscribe_link_absent(self):
        html = _build_html([])
        assert "Unsubscribe" not in html


class TestImpressumLine:
    def test_with_all_vars(self, monkeypatch):
        monkeypatch.setenv("IMPRESSUM_NAME", "Jane Doe")
        monkeypatch.setenv("IMPRESSUM_ADDRESS", "123 Main St")
        monkeypatch.setenv("IMPRESSUM_EMAIL", "jane@example.com")
        line = _impressum_line()
        assert "Jane Doe" in line
        assert "123 Main St" in line
        assert "jane@example.com" in line

    def test_fallback_when_empty(self, monkeypatch):
        monkeypatch.delenv("IMPRESSUM_NAME", raising=False)
        monkeypatch.delenv("IMPRESSUM_ADDRESS", raising=False)
        monkeypatch.delenv("IMPRESSUM_EMAIL", raising=False)
        line = _impressum_line()
        assert line == "StellenScout"
