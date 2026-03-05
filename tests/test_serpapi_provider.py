"""Tests for immermatch.search_api.serpapi_provider — blocklist, staleness, reliability."""

from unittest.mock import patch

import pytest

from immermatch.search_api.serpapi_provider import (
    BLOCKED_PORTALS,
    _is_stale,
    _load_blocked_portals,
    parse_job_results,
)


class TestBlockedPortals:
    def test_loads_from_file(self):
        portals = _load_blocked_portals()
        assert isinstance(portals, set)
        assert len(portals) > 0

    def test_contains_original_domains(self):
        for domain in ("bebee", "jooble", "adzuna", "simplyhired"):
            assert domain in BLOCKED_PORTALS

    def test_contains_new_domains(self):
        for domain in ("kimeta", "zuhausejobs", "whatjobs", "careerjet"):
            assert domain in BLOCKED_PORTALS

    def test_ignores_comments_and_blanks(self):
        for entry in BLOCKED_PORTALS:
            assert not entry.startswith("#")
            assert entry.strip() == entry
            assert len(entry) > 0


class TestIsStaleness:
    @pytest.mark.parametrize(
        "posted_at",
        [
            "30 days ago",
            "30+ days ago",
            "60 days ago",
            "15 days ago",
            "1 month ago",
            "2 months ago",
            "1 year ago",
        ],
    )
    def test_stale(self, posted_at: str):
        assert _is_stale(posted_at) is True

    @pytest.mark.parametrize(
        "posted_at",
        [
            "2 days ago",
            "14 days ago",
            "1 day ago",
            "5 days ago",
            "",
            "Just posted",
        ],
    )
    def test_not_stale(self, posted_at: str):
        assert _is_stale(posted_at) is False

    def test_none_like_empty(self):
        assert _is_stale("") is False


class TestReliabilityClassification:
    def _make_results(self, apply_options: list[dict], posted_at: str = "2 days ago") -> dict:
        return {
            "jobs_results": [
                {
                    "title": "Dev",
                    "company_name": "Co",
                    "location": "Berlin",
                    "description": "A job.",
                    "detected_extensions": {"posted_at": posted_at},
                    "apply_options": apply_options,
                },
            ]
        }

    def test_trusted_portal_gets_aggregator(self):
        results = self._make_results(
            [
                {"title": "LinkedIn", "link": "https://linkedin.com/jobs/1"},
            ]
        )
        jobs = parse_job_results(results)
        assert len(jobs) == 1
        assert jobs[0].reliability == "aggregator"

    def test_company_career_gets_aggregator(self):
        results = self._make_results(
            [
                {"title": "Company Website", "link": "https://example.com/careers"},
            ]
        )
        jobs = parse_job_results(results)
        assert len(jobs) == 1
        assert jobs[0].reliability == "aggregator"

    def test_career_source_gets_aggregator(self):
        results = self._make_results(
            [
                {"title": "Career Page", "link": "https://example.com/apply"},
            ]
        )
        jobs = parse_job_results(results)
        assert len(jobs) == 1
        assert jobs[0].reliability == "aggregator"

    def test_unknown_source_gets_unverified(self):
        results = self._make_results(
            [
                {"title": "RandomSite", "link": "https://randomsite.com/job/1"},
            ]
        )
        jobs = parse_job_results(results)
        assert len(jobs) == 1
        assert jobs[0].reliability == "unverified"

    def test_stale_listing_filtered_out(self):
        results = self._make_results(
            [{"title": "LinkedIn", "link": "https://linkedin.com/jobs/1"}],
            posted_at="30 days ago",
        )
        jobs = parse_job_results(results)
        assert len(jobs) == 0


class TestChipsParam:
    @patch("immermatch.search_api.serpapi_provider.GoogleSearch")
    def test_search_includes_chips(self, mock_search_cls):
        mock_instance = mock_search_cls.return_value
        mock_instance.get_dict.return_value = {"jobs_results": []}

        from immermatch.search_api.serpapi_provider import search_jobs

        with patch.dict("os.environ", {"SERPAPI_KEY": "test-key"}):  # pragma: allowlist secret
            search_jobs("Python Developer", num_results=5)

        params = mock_search_cls.call_args[0][0]
        assert params["chips"] == "date_posted:week"
