"""Tests for search provider helpers and combined provider behavior."""

from immermatch.search_provider import parse_provider_query


class TestParseProviderQuery:
    def test_parses_targeted_query(self):
        target, query = parse_provider_query("provider=SerpApi (Google Jobs)::Python Developer Berlin")
        assert target == "SerpApi (Google Jobs)"
        assert query == "Python Developer Berlin"

    def test_returns_original_when_not_targeted(self):
        target, query = parse_provider_query("Softwareentwickler")
        assert target is None
        assert query == "Softwareentwickler"
