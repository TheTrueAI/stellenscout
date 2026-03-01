"""Tests for search provider helpers and combined provider behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from immermatch.models import ApplyOption, JobListing
from immermatch.search_provider import CombinedSearchProvider, parse_provider_query


def _make_job(title: str, company: str, location: str = "Berlin") -> JobListing:
    return JobListing(
        title=title,
        company_name=company,
        location=location,
        apply_options=[ApplyOption(source="Company Website", url="https://example.com")],
    )


class TestParseProviderQuery:
    def test_parses_targeted_query(self):
        target, query = parse_provider_query("provider=SerpApi (Google Jobs)::Python Developer Berlin")
        assert target == "SerpApi (Google Jobs)"
        assert query == "Python Developer Berlin"

    def test_returns_original_when_not_targeted(self):
        target, query = parse_provider_query("Softwareentwickler")
        assert target is None
        assert query == "Softwareentwickler"


class TestCombinedSearchProvider:
    def test_splits_max_results_budget_across_providers(self):
        p1 = MagicMock()
        p1.name = "Bundesagentur für Arbeit"
        p1.search.return_value = [_make_job(f"BA {i}", f"BA Co {i}") for i in range(3)]

        p2 = MagicMock()
        p2.name = "SerpApi (Google Jobs)"
        p2.search.return_value = [_make_job(f"SERP {i}", f"SERP Co {i}") for i in range(3)]

        provider = CombinedSearchProvider([p1, p2])
        results = provider.search("Developer", "Berlin", max_results=5)

        p1.search.assert_called_once_with("Developer", "Berlin", max_results=3)
        p2.search.assert_called_once_with("Developer", "Berlin", max_results=3)
        assert len(results) == 5

    def test_returns_empty_when_max_results_non_positive(self):
        p1 = MagicMock()
        p1.name = "Bundesagentur für Arbeit"
        p1.search.return_value = [_make_job("BA", "BA Co")]

        provider = CombinedSearchProvider([p1])
        assert provider.search("Developer", "Berlin", max_results=0) == []
        p1.search.assert_not_called()
