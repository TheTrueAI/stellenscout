"""Tests for immermatch.search_api.link_validator."""

from typing import Literal
from unittest.mock import MagicMock, patch

import httpx

from immermatch.models import ApplyOption, JobListing
from immermatch.search_api.link_validator import (
    _is_redirect_to_homepage,
    _path_depth,
    validate_jobs,
)


class TestPathDepth:
    def test_root(self):
        assert _path_depth("https://example.com/") == 0
        assert _path_depth("https://example.com") == 0

    def test_single_segment(self):
        assert _path_depth("https://example.com/careers") == 1

    def test_deep_path(self):
        assert _path_depth("https://example.com/jobs/engineering/req-1234") == 3


class TestIsRedirectToHomepage:
    def test_job_to_homepage(self):
        assert _is_redirect_to_homepage(
            "https://co.com/careers/jobs/1234",
            "https://co.com/careers",
        )

    def test_job_to_root(self):
        assert _is_redirect_to_homepage(
            "https://co.com/jobs/req-1234",
            "https://co.com/",
        )

    def test_job_to_sibling_not_flagged(self):
        assert not _is_redirect_to_homepage(
            "https://co.com/jobs/1234",
            "https://co.com/jobs/5678",
        )

    def test_shallow_original_not_flagged(self):
        assert not _is_redirect_to_homepage(
            "https://co.com/careers",
            "https://co.com/",
        )


def _make_job(
    title: str = "Dev",
    source: str = "serpapi",
    reliability: Literal["verified", "aggregator", "unverified"] = "unverified",
    urls: list[tuple[str, str]] | None = None,
) -> JobListing:
    if urls is None:
        urls = [("LinkedIn", "https://linkedin.com/jobs/1")]
    return JobListing(
        title=title,
        company_name="Co",
        location="Berlin",
        source=source,
        reliability=reliability,
        apply_options=[ApplyOption(source=name, url=url) for name, url in urls],
    )


def _mock_response(status_code: int = 200, headers: dict | None = None) -> httpx.Response:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    return resp


class TestValidateJobs:
    def test_bundesagentur_skipped(self):
        """BA jobs pass through without any HTTP requests."""
        job = _make_job(source="bundesagentur", reliability="verified")
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 1
        assert result[0] is job
        mock_client.head.assert_not_called()

    def test_dead_link_drops_job(self):
        job = _make_job(urls=[("Site", "https://dead.com/jobs/1")])
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.return_value = _mock_response(404)
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 0

    def test_forbidden_drops_job(self):
        job = _make_job(urls=[("Site", "https://gated.com/jobs/1")])
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.return_value = _mock_response(403)
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 0

    def test_live_link_keeps_job(self):
        job = _make_job(urls=[("Site", "https://live.com/jobs/1")])
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.return_value = _mock_response(200)
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 1

    def test_redirect_to_homepage_drops(self):
        job = _make_job(urls=[("Career", "https://co.com/careers/jobs/1234")])
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.return_value = _mock_response(301, headers={"location": "https://co.com/careers"})
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 0

    def test_redirect_to_sibling_keeps(self):
        job = _make_job(urls=[("Site", "https://co.com/jobs/1234")])
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.return_value = _mock_response(302, headers={"location": "https://co.com/jobs/5678"})
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 1

    def test_mixed_links_keeps_live_ones(self):
        job = _make_job(
            urls=[
                ("Dead", "https://dead.com/jobs/1"),
                ("Live", "https://live.com/jobs/1"),
            ]
        )

        def _head_side_effect(url, **kwargs):
            if "dead.com" in url:
                return _mock_response(410)
            return _mock_response(200)

        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.side_effect = _head_side_effect
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 1
        assert len(result[0].apply_options) == 1
        assert result[0].apply_options[0].source == "Live"

    def test_network_error_treated_as_alive(self):
        """Transient network errors should not penalize the job."""
        job = _make_job(urls=[("Slow", "https://slow.com/jobs/1")])
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.side_effect = httpx.ConnectError("timeout")
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([job])
        assert len(result) == 1

    def test_only_serpapi_jobs_checked(self):
        """BA jobs + serpapi jobs: only serpapi jobs get HEAD requests."""
        ba_job = _make_job(title="BA", source="bundesagentur", reliability="verified")
        serp_job = _make_job(title="Serp", source="serpapi")
        with patch("immermatch.search_api.link_validator.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.head.return_value = _mock_response(200)
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = validate_jobs([ba_job, serp_job])
        assert len(result) == 2
        # Only the serpapi job's URL should have been checked
        assert mock_client.head.call_count == 1
