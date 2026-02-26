"""Tests for stellenscout.emailer — HTML builder pure functions."""

from unittest.mock import patch

import pytest

from stellenscout.emailer import (
    _build_html,
    _build_job_row,
    _impressum_line,
    _safe_url,
    send_verification_email,
    send_welcome_email,
)


class TestSafeUrl:
    def test_allows_https(self):
        assert _safe_url("https://example.com") == "https://example.com"

    def test_allows_http(self):
        assert _safe_url("http://example.com") == "http://example.com"

    def test_blocks_javascript(self):
        assert _safe_url("javascript:alert(1)") == "#"

    def test_blocks_data_uri(self):
        assert _safe_url("data:text/html,<h1>hi</h1>") == "#"

    def test_escapes_quotes_in_url(self):
        assert "&amp;" in _safe_url("https://example.com?a=1&b=2")

    def test_empty_string(self):
        assert _safe_url("") == ""


class TestHtmlEscapingInJobRow:
    def test_escapes_title_with_html(self):
        html = _build_job_row({"title": "<script>alert(1)</script>", "company": "Co", "url": "https://x.com"})
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_escapes_company_with_html(self):
        html = _build_job_row({"title": "Dev", "company": "<b>evil</b>", "url": "https://x.com"})
        assert "<b>evil</b>" not in html
        assert "&lt;b&gt;" in html

    def test_blocks_javascript_url(self):
        html = _build_job_row({"title": "Dev", "company": "Co", "url": "javascript:alert(1)"})
        assert "javascript:" not in html


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

    def test_contains_location_when_provided(self):
        html = _build_job_row({"title": "Dev", "company": "Co", "score": 80, "url": "#", "location": "Munich"})
        assert "Munich" in html
        assert "&#128205;" in html

    def test_omits_location_when_missing(self):
        html = _build_job_row({"title": "Dev", "company": "Co", "score": 80, "url": "#"})
        assert "&#128205;" not in html

    def test_view_job_button_present(self):
        html = _build_job_row({"title": "Dev", "company": "Co", "score": 80, "url": "https://example.com/job"})
        assert "View Job" in html
        assert "https://example.com/job" in html


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

    def test_contains_target_location_in_header(self):
        html = _build_html([], target_location="Munich")
        assert "Jobs in Munich" in html

    def test_omits_location_when_empty(self):
        html = _build_html([], target_location="")
        assert "Jobs in" not in html

    def test_contains_match_stats(self):
        jobs = [
            {"title": "Dev", "company": "Co", "score": 85, "url": "#"},
            {"title": "Eng", "company": "Co", "score": 75, "url": "#"},
        ]
        html = _build_html(jobs)
        assert "1 excellent" in html
        assert "1 good" in html

    def test_contains_subscriber_explanation(self):
        html = _build_html([])
        assert "You're receiving this because you subscribed to StellenScout" in html


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


class TestSendWelcomeEmail:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        with pytest.raises(ValueError, match="RESEND_API_KEY"):
            send_welcome_email("user@example.com")

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_contains_location(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_welcome_email("user@example.com", target_location="Munich")
        html = mock_send.call_args[0][0]["html"]
        assert "Munich" in html

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_contains_subscription_days(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_welcome_email("user@example.com", subscription_days=30)
        html = mock_send.call_args[0][0]["html"]
        assert "30 days" in html

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_contains_privacy_link(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_welcome_email("user@example.com", privacy_url="https://app.test/privacy")
        html = mock_send.call_args[0][0]["html"]
        assert "https://app.test/privacy" in html

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_without_location(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_welcome_email("user@example.com", target_location="")
        html = mock_send.call_args[0][0]["html"]
        assert "&#128205;" not in html
        assert "daily job digest is now active" in html

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_includes_impressum(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        monkeypatch.setenv("IMPRESSUM_NAME", "Jane Doe")
        send_welcome_email("user@example.com")
        html = mock_send.call_args[0][0]["html"]
        assert "Jane Doe" in html

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_contains_unsubscribe_link(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_welcome_email("user@example.com", unsubscribe_url="https://app.test/unsubscribe?token=abc")
        html = mock_send.call_args[0][0]["html"]
        assert "https://app.test/unsubscribe?token=abc" in html
        assert "Unsubscribe" in html
        headers = mock_send.call_args[0][0].get("headers", {})
        assert "List-Unsubscribe" in headers

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_welcome_no_unsubscribe_footer_link_when_empty(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_welcome_email("user@example.com", unsubscribe_url="")
        html = mock_send.call_args[0][0]["html"]
        assert ">Unsubscribe</a>" not in html
        assert "headers" not in mock_send.call_args[0][0]


class TestSendVerificationEmail:
    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_verification_contains_confirm_button(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_verification_email("user@example.com", "https://app.test/verify?token=xyz")
        html = mock_send.call_args[0][0]["html"]
        assert "Confirm subscription" in html
        assert "https://app.test/verify?token=xyz" in html

    @patch("stellenscout.emailer.resend.Emails.send", return_value={"id": "123"})
    def test_verification_contains_feature_preview(self, mock_send, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        send_verification_email("user@example.com", "https://app.test/verify?token=xyz")
        html = mock_send.call_args[0][0]["html"]
        assert "AI scores every job" in html
        assert "Daily digest" in html
